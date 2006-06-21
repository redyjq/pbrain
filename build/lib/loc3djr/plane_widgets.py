# http://www.vtk.org/doc/nightly/html/classvtkInteractorStyle.html defines the key events
from __future__ import division

import vtk

import gtk

import re, time
from gtk import gdk
from GtkGLExtVTKRenderWindowInteractor import GtkGLExtVTKRenderWindowInteractor
from GtkGLExtVTKRenderWindow import GtkGLExtVTKRenderWindow
from scipy import array
from scipy import mean
from image_reader import widgets, GladeHandlers
from pbrainlib.gtkutils import error_msg, simple_msg, ButtonAltLabel, \
     str2posnum_or_err, ProgressBarDialog, make_option_menu, MyToolbar
from matplotlib.cbook import Bunch

from markers import Marker, RingActor
from events import EventHandler, UndoRegistry, Viewer
from shared import shared
from surf_renderer import SurfRendererProps, SurfRenderWindow

import scipy

INTERACT_CURSOR, MOVE_CURSOR, COLOR_CURSOR, SELECT_CURSOR, DELETE_CURSOR, LABEL_CURSOR = gtk.gdk.ARROW, gtk.gdk.HAND2, gtk.gdk.SPRAYCAN, gtk.gdk.TCROSS, gtk.gdk.X_CURSOR, gtk.gdk.PENCIL
        
def move_pw_to_point(pw, xyz):

    n = pw.GetNormal()
    o = pw.GetOrigin()
    pxyz = [0,0,0]
    vtk.vtkPlane.ProjectPoint(xyz, o, n, pxyz)
    transform = vtk.vtkTransform()
    transform.Translate(xyz[0]-pxyz[0], xyz[1]-pxyz[1], xyz[2]-pxyz[2])
    p1 = transform.TransformPoint(pw.GetPoint1())
    p2 = transform.TransformPoint(pw.GetPoint2())
    o = transform.TransformPoint(o)

    pw.SetOrigin(o)                
    pw.SetPoint1(p1)
    pw.SetPoint2(p2)
    pw.UpdatePlacement()



    
    
class MarkerWindowInteractor(GtkGLExtVTKRenderWindowInteractor, Viewer):
    def __init__(self):
        GtkGLExtVTKRenderWindowInteractor.__init__(self)
        EventHandler().attach(self)
        self.interactButtons = (1,2,3)
        self.renderOn = 1
        self.Initialize()
        self.Start()

        self.renderer = vtk.vtkRenderer()
        self.renWin = self.GetRenderWindow()
        self.renWin.AddRenderer(self.renderer)
        self.interactor = self.renWin.GetInteractor()
        #self.camera = self.renderer.GetActiveCamera()

        
        self.pressFuncs = {1 : self._Iren.LeftButtonPressEvent,
                           2 : self._Iren.MiddleButtonPressEvent,
                           3 : self._Iren.RightButtonPressEvent}
        self.releaseFuncs = {1 : self._Iren.LeftButtonReleaseEvent,
                             2 : self._Iren.MiddleButtonReleaseEvent,
                             3 : self._Iren.RightButtonReleaseEvent}

        self.pressHooks = {}
        self.releaseHooks = {}
        self.lastLabel = None
        
    def Render(self):
        if self.renderOn:
            GtkGLExtVTKRenderWindowInteractor.Render(self)


    def mouse1_mode_change(self, event):
        """
        Give derived classes toclean up any observers, etc, before
        switching to new mode
        """
        
        pass

    def update_viewer(self, event, *args):
        if event.find('mouse1')==0:
            self.mouse1_mode_change(event)
        if event=='mouse1 interact':
            self.set_mouse1_to_interact()
        elif event=='mouse1 color':
            self.set_mouse1_to_color()
        elif event=='mouse1 delete':
            self.set_mouse1_to_delete()
        elif event=='mouse1 label':
            self.set_mouse1_to_label()
        elif event=='mouse1 select':
            self.set_mouse1_to_select()
        elif event=='mouse1 move':
            self.set_mouse1_to_move()
        elif event=='render off':
            self.renderOn = 0
        elif event=='render on':
            self.renderOn = 1
            self.Render()
        elif event=='set image data':
            imageData = args[0]
            self.set_image_data(imageData)
            self.Render()
        elif event=='render':
            self.Render()
            


    def get_marker_at_point(self):    
        raise NotImplementedError

    def set_image_data(self, imageData):
        pass
    
    def set_select_mode(self):
        pass

    def set_interact_mode(self):
        pass
    
    def set_mouse1_to_interact(self):


        try: del self.pressHooks[1]
        except KeyError: pass

        try: del self.releaseHooks[1]
        except KeyError: pass
        self.set_interact_mode()

        cursor = gtk.gdk.Cursor (INTERACT_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)

    def set_mouse1_to_move(self):

        self.set_select_mode()
        cursor = gtk.gdk.Cursor (MOVE_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)

    
    def set_mouse1_to_delete(self):
        

        def button_up(*args):
            pass

        def button_down(*args):
            marker = self.get_marker_at_point()
            if marker is None: return
            EventHandler().remove_marker(marker)

        self.pressHooks[1] = button_down
        self.releaseHooks[1] = button_up

        self.set_select_mode()
        cursor = gtk.gdk.Cursor (DELETE_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)

    def set_mouse1_to_select(self):
        
        def button_up(*args):
            pass

        def button_down(*args):
            marker = self.get_marker_at_point()
            if marker is None: return
            isSelected = EventHandler().is_selected(marker)
            if self.interactor.GetControlKey():
                if isSelected: EventHandler().remove_selection(marker)
                else: EventHandler().add_selection(marker)
            else: EventHandler().select_new(marker)

        self.pressHooks[1] = button_down
        self.releaseHooks[1] = button_up

        self.set_select_mode()
        cursor = gtk.gdk.Cursor (SELECT_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)

    def set_mouse1_to_label(self):

        def button_up(*args):
            pass

        def button_down(*args):
            marker = self.get_marker_at_point()
            if marker is None: return
            dlg = gtk.Dialog('Marker Label')
            dlg.show()

            
            frame = gtk.Frame('Marker Label')
            frame.show()
            frame.set_border_width(5)
            dlg.vbox.pack_start(frame)

            entry = gtk.Entry()
            entry.set_activates_default(True)            
            entry.show()

            label = marker.get_label()
            defaultLabel = label
            if defaultLabel=='' and self.lastLabel is not None:
                m = re.match('(.+?)(\d+)', self.lastLabel)
                if m:
                    defaultLabel = m.group(1) + str(int(m.group(2))+1)
                
                
            entry.set_text(defaultLabel)
            frame.add(entry)
            
            dlg.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
            dlg.add_button(gtk.STOCK_OK, gtk.RESPONSE_OK)
            dlg.set_default_response(gtk.RESPONSE_OK)
            response = dlg.run()
            if response == gtk.RESPONSE_OK:
                label = entry.get_text()
                if label == '': return
                oldLabel = marker.get_label()
                UndoRegistry().push_command(
                    EventHandler().notify, 'label marker', marker, oldLabel)
                EventHandler().notify('label marker', marker, label)
                self.lastLabel = label
            dlg.destroy()
            self.Render()
            

        self.pressHooks[1] = button_down
        self.releaseHooks[1] = button_up
        self.set_select_mode()
        cursor = gtk.gdk.Cursor (LABEL_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)
        
    def set_mouse1_to_color(self):

        def button_up(*args):
            pass

        def button_down(*args):
            marker = self.get_marker_at_point()
            if marker is None: return
            color = EventHandler().get_default_color()
            oldColor = marker.get_color()
            UndoRegistry().push_command(
                EventHandler().notify, 'color marker', marker, oldColor)
            EventHandler().notify('color marker', marker, color)

        self.pressHooks[1] = button_down
        self.releaseHooks[1] = button_up
        self.set_select_mode()

        cursor = gtk.gdk.Cursor (COLOR_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)


    def OnButtonDown(self, wid, event):
        """Mouse button pressed."""

        self.lastCamera = self.get_camera_fpu()
        m = self.get_pointer()
        ctrl, shift = self._GetCtrlShift(event)
        self._Iren.SetEventInformationFlipY(m[0], m[1], ctrl, shift,
                                            chr(0), 0, None)

        if event.button in self.interactButtons:
            self.pressFuncs[event.button]()            

        try: self.pressHooks[event.button]()
        except KeyError: pass

        button = event.button

        True

    def OnButtonUp(self, wid, event):
        """Mouse button released."""
        m = self.get_pointer()
        ctrl, shift = self._GetCtrlShift(event)
        self._Iren.SetEventInformationFlipY(m[0], m[1], ctrl, shift,
                                            chr(0), 0, None)


        if event.button in self.interactButtons:
            self.releaseFuncs[event.button]()            

        try: self.releaseHooks[event.button]()
        except KeyError: pass

        thisCamera = self.get_camera_fpu()
        try: self.lastCamera
        except AttributeError: pass  # this
        else:
            if thisCamera != self.lastCamera:
                UndoRegistry().push_command(self.set_camera, self.lastCamera)

        return True



    def get_camera_fpu(self):
        camera = self.renderer.GetActiveCamera()
        return (camera.GetFocalPoint(),
                camera.GetPosition(),
                camera.GetViewUp())
                
    def set_camera(self, fpu):
        camera = self.renderer.GetActiveCamera()
        focal, position, up = fpu
        camera.SetFocalPoint(focal)
        camera.SetPosition(position)
        camera.SetViewUp(up)
        self.renderer.ResetCameraClippingRange()
        self.Render()

    def get_plane_points(self, pw):
        return pw.GetOrigin(), pw.GetPoint1(), pw.GetPoint2()

    def set_plane_points(self, pw, pnts):
        o, p1, p2 = pnts
        pw.SetOrigin(o)
        pw.SetPoint1(p1)
        pw.SetPoint2(p2)
        pw.UpdatePlacement()

        
class PlaneWidgetsXYZ(MarkerWindowInteractor):
    def __init__(self, imageData=None):
        MarkerWindowInteractor.__init__(self)

        self.interactButtons = (1,2,3)
        self.sharedPicker = vtk.vtkCellPicker()
        self.sharedPicker.SetTolerance(0.005)
        self.SetPicker(self.sharedPicker)
        
        self.pwX = vtk.vtkImagePlaneWidget()
        self.pwY = vtk.vtkImagePlaneWidget()
        self.pwZ = vtk.vtkImagePlaneWidget()
        self.textActors = {}
        self.boxes = {}

        self.set_image_data(imageData)
        self.Render()

    def set_image_data(self, imageData):
        if imageData is None: return 
        self.imageData = imageData
        extent = self.imageData.GetExtent()
        frac = 0.3

        self._plane_widget_boilerplate(
            self.pwX, key='x', color=(1,0,0),
            index=frac*(extent[1]-extent[0]),
            orientation=0)

        self._plane_widget_boilerplate(
            self.pwY, key='y', color=(1,1,0),
            index=frac*(extent[3]-extent[2]),
            orientation=1)
        self.pwY.SetLookupTable(self.pwX.GetLookupTable())

        self._plane_widget_boilerplate(
            self.pwZ, key='z', color=(0,0,1),
            index=frac*(extent[5]-extent[4]),
            orientation=2)
        self.pwZ.SetLookupTable(self.pwX.GetLookupTable())
        
        self.pwX.SetResliceInterpolateToCubic()
        self.pwY.SetResliceInterpolateToCubic()
        self.pwZ.SetResliceInterpolateToCubic()
        #self.pwZ.SetResliceInterpolateToNearestNeighbour()
        self.camera = self.renderer.GetActiveCamera()

        center = imageData.GetCenter()
        spacing = imageData.GetSpacing()
        bounds = imageData.GetBounds()
        pos = center[0], center[1], center[2] - max(bounds)*2
        fpu = center, pos, (0,-1,0)
        self.set_camera(fpu)


        #print self.pwX.GetResliceOutput().GetSpacing(), imageData.GetSpacing()
    def get_marker_at_point(self):
        
        x, y = self.GetEventPosition()
        picker = vtk.vtkPropPicker()
        picker.PickProp(x, y, self.renderer, EventHandler().get_markers())
        actor = picker.GetActor()
        return actor

    def update_viewer(self, event, *args):
        MarkerWindowInteractor.update_viewer(self, event, *args)
        if event=='add marker':
            marker = args[0]
            self.add_marker(marker)
        elif event=='remove marker':
            marker = args[0]
            self.remove_marker(marker)
        elif event=='color marker':
            marker, color = args
            marker.set_color(color)
        elif event=='label marker':
            marker, label = args
            marker.set_label(label)
            
            text = vtk.vtkVectorText()
            text.SetText(marker.get_label())
            textMapper = vtk.vtkPolyDataMapper()
            textMapper.SetInput(text.GetOutput())
            textActor = self.textActors[marker]
            textActor.SetMapper(textMapper)

        elif event=='move marker':
            marker, center = args
            marker.set_center(center)
            #update the select boxes and text actor
            textActor = self.textActors[marker]
            size = marker.get_size()
            textActor.SetScale(size, size, size)
            x,y,z = marker.get_center()
            textActor.SetPosition(x+size, y+size, z+size)

            if self.boxes.has_key(marker):
                selectActor = self.boxes[marker]
                boxSource = vtk.vtkCubeSource()
                boxSource.SetBounds(marker.GetBounds())
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInput(boxSource.GetOutput())
                selectActor.SetMapper(mapper)
                
                
        elif event=='labels on':
            actors = self.textActors.values()
            for actor in actors:
                actor.VisibilityOn()
        elif event=='labels off':
            actors = self.textActors.values()
            for actor in actors:
                actor.VisibilityOff()
        elif event=='select marker':
            marker = args[0]
            boxSource = vtk.vtkCubeSource()
            boxSource.SetBounds(marker.GetBounds())
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInput(boxSource.GetOutput())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor( marker.get_color() )
            actor.GetProperty().SetRepresentationToWireframe()
            actor.GetProperty().SetLineWidth(2.0)
            self.renderer.AddActor(actor)
            self.boxes[marker] = actor
        elif event=='unselect marker':
            marker = args[0]
            actor = self.boxes[marker]
            self.renderer.RemoveActor(actor)

        
        self.Render()
        
        
    def add_marker(self, marker):
        self.renderer.AddActor(marker)

        text = vtk.vtkVectorText()
        text.SetText(marker.get_label())
        textMapper = vtk.vtkPolyDataMapper()
        textMapper.SetInput(text.GetOutput())

        textActor = vtk.vtkFollower()
        textActor.SetMapper(textMapper)
        size = marker.get_size()
        textActor.SetScale(size, size, size)
        x,y,z = marker.get_center()
        textActor.SetPosition(x+size, y+size, z+size)
        textActor.SetCamera(self.camera)
        textActor.GetProperty().SetColor(marker.get_label_color())
        if EventHandler().get_labels_on():
            textActor.VisibilityOn()
        else:
            textActor.VisibilityOff()


        self.textActors[marker] = textActor
        self.renderer.AddActor(textActor)

    def remove_marker(self, marker):
        self.renderer.RemoveActor(marker)
        self.renderer.RemoveActor(self.textActors[marker])
        del self.textActors[marker]

    def _plane_widget_boilerplate(self, pw, key, color, index, orientation):

        pw.TextureInterpolateOn()
        #pw.SetResliceInterpolateToCubic()
        pw.SetKeyPressActivationValue(key)
        pw.SetPicker(self.sharedPicker)
        pw.GetPlaneProperty().SetColor(color)
        pw.DisplayTextOn()
        pw.SetInput(self.imageData)
        pw.SetPlaneOrientation(orientation)
        pw.SetSliceIndex(int(index))
        pw.SetInteractor(self.interactor)
        pw.On()
        pw.UpdatePlacement()

    def get_plane_widget_x(self):
        return self.pwX

    def get_plane_widget_y(self):
        return self.pwY

    def get_plane_widget_z(self):
        return self.pwZ

    def get_plane_widgets_xyz(self):
        return (self.get_plane_widget_x(),
                self.get_plane_widget_y(),
                self.get_plane_widget_z())

    def snap_view_to_point(self, xyz):

        # project the point onto the plane, find the distance between
        # xyz and the projected point, then move the plane along it's
        # normal that distance

        #todo: undo
        move_pw_to_point(self.pwX, xyz)
        move_pw_to_point(self.pwY, xyz)
        move_pw_to_point(self.pwZ, xyz)
        self.Render()
        EventHandler().notify('observers update plane')
        

    def set_plane_points_xyz(self, pxyz):
        px, py, pz = pxyz
        self.set_plane_points(self.pwX, px)
        self.set_plane_points(self.pwY, py)
        self.set_plane_points(self.pwZ, pz)
        self.Render()
        EventHandler().notify('observers update plane')

    def set_select_mode(self):
        self.interactButtons = (2,3)

    def set_interact_mode(self):
        self.interactButtons = (1,2,3)

    def OnButtonDown(self, wid, event):
        """Mouse button pressed."""


        self.lastPntsXYZ = ( self.get_plane_points(self.pwX),
                             self.get_plane_points(self.pwY),
                             self.get_plane_points(self.pwZ))
                             

        MarkerWindowInteractor.OnButtonDown(self, wid, event)
        return True

    def OnButtonUp(self, wid, event):
        """Mouse button released."""
        
        if not hasattr(self, 'lastPntsXYZ'): return
        MarkerWindowInteractor.OnButtonUp(self, wid, event)
        pntsXYZ = ( self.get_plane_points(self.pwX),
                    self.get_plane_points(self.pwY),
                    self.get_plane_points(self.pwZ))


        if pntsXYZ != self.lastPntsXYZ:
            UndoRegistry().push_command(
                self.set_plane_points_xyz, self.lastPntsXYZ)


        return True




class PlaneWidgetObserver(MarkerWindowInteractor):
    def __init__(self, planeWidget, owner, orientation, imageData=None):
        MarkerWindowInteractor.__init__(self)
        self.interactButtons = (1,2,3)
        self.pw = planeWidget
        self.owner = owner
        self.orientation = orientation
        self.observer = vtk.vtkImagePlaneWidget()

        self.camera = self.renderer.GetActiveCamera()

        self.ringActors = vtk.vtkActorCollection()
        self.defaultRingLine = 1
        self.textActors = {}
        self.hasData = 0

        self.set_image_data(imageData)
        self.lastTime = 0
        self.set_mouse1_to_move()
        
    def set_image_data(self, imageData):
        if imageData is None: return 
        self.imageData = imageData
        if not self.hasData:
            self.pw.AddObserver('InteractionEvent', self.interaction_event)
            self.connect("scroll_event", self.scroll_widget_slice)
            self.hasData = 1

        # make cursor invisible
        self.observer.GetCursorProperty().SetOpacity(0.0)
        
        self.observer.TextureInterpolateOn()            
        self.observer.TextureInterpolateOn()
        self.observer.SetKeyPressActivationValue(
            self.pw.GetKeyPressActivationValue())
        self.observer.GetPlaneProperty().SetColor(0,0,0)
        self.observer.SetResliceInterpolate(
            self.pw.GetResliceInterpolate())
        self.observer.SetLookupTable(self.pw.GetLookupTable())        
        self.observer.DisplayTextOn()
        #self.observer.GetMarginProperty().EdgeVisibilityOff()  # turn off edges??
        self.observer.SetInput(imageData)
        self.observer.SetInteractor(self.interactor)
        self.observer.On()
        self.observer.InteractionOff()
        self.update_plane()
        if self.orientation==0: up = (0,0,1)
        elif self.orientation==1: up = (0,0,1)
        elif self.orientation==2: up = (0,-1,0)
        else:
            raise ValueError, 'orientation must be in 0,1,2'

        center = self.observer.GetCenter()
        normal = self.pw.GetNormal()
        spacing =imageData.GetSpacing()
        bounds = imageData.GetBounds()

        offset = max(bounds)
        pos = (center[0] + normal[0]*offset,
               center[1] - normal[1]*offset,
               center[2] - normal[2]*offset)
        
        self.set_camera((center, pos, up))
        self.resetCamera = (center, pos, up)

        #self.sliceIncrement = spacing[self.orientation]
        self.sliceIncrement = 0.1

    def mouse1_mode_change(self, event):
        try: self.moveEvent
        except AttributeError: pass
        else: self.observer.RemoveObserver(self.moveEvent)

        try: self.startEvent
        except AttributeError: pass
        else: self.observer.RemoveObserver(self.startEvent)

        try: self.endEvent
        except AttributeError: pass
        else: self.observer.RemoveObserver(self.endEvent)

        
    def set_mouse1_to_move(self):


        self.markerAtPoint = None
        self.pressed1 = 0

        def move(*args):
            if self.markerAtPoint is None: return 
            xyz = self.get_cursor_position_world()
            EventHandler().notify(
                'move marker', self.markerAtPoint, xyz)

        def button_down(*args):
            self.markerAtPoint = self.get_marker_at_point()
            if self.markerAtPoint is not None:
                self.lastPos = self.markerAtPoint.get_center()

        def button_up(*args):
            if self.markerAtPoint is None: return
            thisPos = self.markerAtPoint.get_center()

            def undo_move(marker):
                marker.set_center(self.lastPos)
                ra = self.get_actor_for_marker(marker)
                ra.update()
                self.Render()

            if thisPos != self.lastPos:
                UndoRegistry().push_command(undo_move, self.markerAtPoint)
            self.markerAtPoint = None
            

        self.pressHooks[1] = button_down
        self.releaseHooks[1] = button_up

        #self.startEvent = self.observer.AddObserver(
        #    'StartInteractionEvent', start_iact)
        #self.endEvent = self.observer.AddObserver(
        #    'EndInteractionEvent', end_iact)
        self.moveEvent = self.observer.AddObserver(
            'InteractionEvent', move)

        #self.set_select_mode()

        cursor = gtk.gdk.Cursor (MOVE_CURSOR)
        if self.window is not None:
            self.window.set_cursor (cursor)

    def set_select_mode(self):
        return

        self.defaultRingLine = 3
        actors = self.get_ring_actors_as_list()
        for actor in actors:
            actor.set_line_width(self.defaultRingLine)
            actor.update()
        self.Render()

    def set_interact_mode(self):
        

        self.interactButtons = (1,2,3)
        self.set_mouse1_to_move()
        return
    
        self.defaultRingLine = 1
        actors = self.get_ring_actors_as_list()
        for actor in actors:
            actor.set_line_width(self.defaultRingLine)
            actor.update()
        self.Render()
        self.set_mouse1_to_move()


    def get_marker_at_point(self):
        xyz = self.get_cursor_position_world()
        for actor in self.get_ring_actors_as_list():
            if not actor.GetVisibility(): continue
            marker = actor.get_marker()
            if marker is None: return None
            if marker.contains(xyz): return marker
        return None

    def get_plane_points(self):
        return self.pw.GetOrigin(), self.pw.GetPoint1(), self.pw.GetPoint2()

    def set_plane_points(self, pnts):
        o, p1, p2 = pnts
        self.pw.SetOrigin(o)
        self.pw.SetPoint1(p1)
        self.pw.SetPoint2(p2)
        self.pw.UpdatePlacement()
        self.update_plane()

    def OnButtonDown(self, wid, event):
        if not self.hasData: return 
        self.lastPnts = self.get_plane_points()


        if event.button==1:
            self.observer.InteractionOn()

        ret =  MarkerWindowInteractor.OnButtonDown(self, wid, event)
        return ret
    def OnButtonUp(self, wid, event):
        if not hasattr(self, 'lastPnts'): return
        #calling this before base class freezes the cursor at last pos
        if not self.hasData: return 
        if  event.button==1:
            self.observer.InteractionOff()
        MarkerWindowInteractor.OnButtonUp(self, wid, event)            

        pnts = self.get_plane_points()

        if pnts != self.lastPnts:
            UndoRegistry().push_command(self.set_plane_points, self.lastPnts)
        return True
    

    def scroll_depth(self, step):
        # step along the normal
        p1 = array(self.pw.GetPoint1())
        p2 = array(self.pw.GetPoint2())

        origin = self.pw.GetOrigin()
        normal = self.pw.GetNormal()
        newPlane = vtk.vtkPlane()
        newPlane.SetNormal(normal)
        newPlane.SetOrigin(origin)
        newPlane.Push(step)
        newOrigin = newPlane.GetOrigin()

        delta = array(newOrigin) - array(origin) 
        p1 += delta
        p2 += delta
            
        self.pw.SetPoint1(p1)
        self.pw.SetPoint2(p2)
        self.pw.SetOrigin(newOrigin)
        self.pw.UpdatePlacement()
        self.update_plane()
        
    def scroll_axis1(self, step):
        #rotate around axis 1
        axis1 = [0,0,0]
        self.pw.GetVector1(axis1)
        transform = vtk.vtkTransform()

        axis2 = [0,0,0]
        self.pw.GetVector2(axis2)

        transform = vtk.vtkTransform()
        transform.RotateWXYZ(step,
                             (axis1[0] + 0.5*axis2[0],
                              axis1[1] + 0.5*axis2[2],
                              axis1[2] + 0.5*axis2[2]))
        o, p1, p2 = self.get_plane_points()
        o = transform.TransformPoint(o)
        p1 = transform.TransformPoint(p1)
        p2 = transform.TransformPoint(p2)
        self.set_plane_points((o, p1, p2))
        self.update_plane()
        
    def scroll_axis2(self, step):
        axis1 = [0,0,0]
        self.pw.GetVector2(axis1)
        transform = vtk.vtkTransform()

        axis2 = [0,0,0]
        self.pw.GetVector1(axis2)

        transform = vtk.vtkTransform()
        transform.RotateWXYZ(step,
                             (axis1[0] + 0.5*axis2[0],
                              axis1[1] + 0.5*axis2[2],
                              axis1[2] + 0.5*axis2[2]))
        o, p1, p2 = self.get_plane_points()
        o = transform.TransformPoint(o)
        p1 = transform.TransformPoint(p1)
        p2 = transform.TransformPoint(p2)
        self.set_plane_points((o, p1, p2))
        self.update_plane()


    def scroll_widget_slice(self, widget, event):

        now = time.time()
        elapsed = now - self.lastTime

        if elapsed < 0.001: return # swallow repeatede events

        if event.direction == gdk.SCROLL_UP: step = 1
        elif event.direction == gdk.SCROLL_DOWN: step = -1

        if self.interactor.GetShiftKey():
            self.scroll_axis1(step)
        elif self.interactor.GetControlKey():
            self.scroll_axis2(step)
        else:
            self.scroll_depth(step*self.sliceIncrement)
        
        

        self.get_pwxyz().Render()
        self.update_rings()
        self.Render()
        self.lastTime = time.time()

    def update_rings(self):
            
        self.ringActors.InitTraversal()
        numActors = self.ringActors.GetNumberOfItems()
        for i in range(numActors):
            actor = self.ringActors.GetNextActor()
            #print i, actor
            vis = actor.update()
            textActor = self.textActors[actor.get_marker()]
            if vis and EventHandler().get_labels_on():
                textActor.VisibilityOn()
            else:
                textActor.VisibilityOff()


    def interaction_event(self, *args):
        self.update_plane()
        self.update_rings()
        self.Render()

    def update_plane(self):

        p1 = self.pw.GetPoint1()
        p2 = self.pw.GetPoint2()
        o = self.pw.GetOrigin()
        self.observer.SetPoint1(p1)
        self.observer.SetPoint2(p2)
        self.observer.SetOrigin(o)
        self.observer.UpdatePlacement()
        self.renderer.ResetCameraClippingRange()

    def OnKeyPress(self, wid, event=None):
        
        if (event.keyval == gdk.keyval_from_name("i") or
            event.keyval == gdk.keyval_from_name("I")):

            xyz = self.get_cursor_position_world()
            if xyz is None: return 

            marker = Marker(xyz=xyz,
                            rgb=EventHandler().get_default_color())

            EventHandler().add_marker(marker)
            return True

        elif (event.keyval == gdk.keyval_from_name("r") or
              event.keyval == gdk.keyval_from_name("R")):
            self.set_camera(self.resetCamera)
            return True
        
        return MarkerWindowInteractor.OnKeyPress(self, wid, event)


    def update_viewer(self, event, *args):
        MarkerWindowInteractor.update_viewer(self, event, *args)
        if event=='add marker':
            marker = args[0]
            self.add_ring_actor(marker)
        elif event=='remove marker':
            marker = args[0]
            self.remove_ring_actor(marker)
        elif event=='move marker':
            # ring actor will update automatically because it shares
            # the sphere source
            marker, pos = args
            textActor = self.textActors[marker]
            textActor.SetPosition(pos)

        elif event=='color marker':
            marker, color = args
            actor = self.get_actor_for_marker(marker)
            actor.update()
        elif event=='label marker':
            marker, label = args
            marker.set_label(label)
            text = vtk.vtkVectorText()
            text.SetText(marker.get_label())
            textMapper = vtk.vtkPolyDataMapper()
            textMapper.SetInput(text.GetOutput())
            textActor = self.textActors[marker]
            textActor.SetMapper(textMapper)
        elif event=='observers update plane':
            self.update_plane()
            
        self.update_rings()
        self.Render()

    def add_ring_actor(self, marker):
        ringActor = RingActor(marker, self.pw, lineWidth=self.defaultRingLine)
        vis = ringActor.update()
        self.renderer.AddActor(ringActor)
        self.ringActors.AddItem(ringActor)


        # a hack to keep vtk from casting my class when I put it in
        # the collection.  If I don't register some func, I lose all
        # the derived methods        
        self.observer.AddObserver('EndInteractionEvent', ringActor.silly_hack)

        text = vtk.vtkVectorText()
        text.SetText(marker.get_label())
        textMapper = vtk.vtkPolyDataMapper()
        textMapper.SetInput(text.GetOutput())

        textActor = vtk.vtkFollower()
        textActor.SetMapper(textMapper)
        size = 2*marker.get_size()
        textActor.SetScale(size, size, size)
        x,y,z = marker.get_center()
        textActor.SetPosition(x, y, z)
        textActor.SetCamera(self.camera)
        textActor.GetProperty().SetColor(marker.get_label_color())
        if EventHandler().get_labels_on() and vis:
            textActor.VisibilityOn()
        else:
            textActor.VisibilityOff()

        self.textActors[marker] = textActor
        self.renderer.AddActor(textActor)


    def remove_ring_actor(self, marker):
        actor = self.get_actor_for_marker(marker)
        if actor is not None:
            self.renderer.RemoveActor(actor)
            self.ringActors.RemoveItem(actor)

        textActor = self.textActors[marker]
        self.renderer.RemoveActor(textActor)
        del self.textActors[marker]
        
    def get_actor_for_marker(self, marker):
        self.ringActors.InitTraversal()
        numActors = self.ringActors.GetNumberOfItems()
        for i in range(numActors):
            actor = self.ringActors.GetNextActor()
            if marker is actor.get_marker():
                return actor
        return None

    def get_ring_actors_as_list(self):

        self.ringActors.InitTraversal()
        numActors = self.ringActors.GetNumberOfItems()
        l = [None]*numActors
        for i in range(numActors):
            l[i] = self.ringActors.GetNextActor()
        return l

    def get_cursor_position_world(self):
        x, y = self.GetEventPosition()
        xyz = [x, y, 0.0]
        picker = vtk.vtkWorldPointPicker()
        picker.Pick(xyz, self.renderer)
        ppos = picker.GetPickPosition()
        return ppos
        #pos = self.get_cursor_position()
        #if pos is None: return None
        #world =  self.obs_to_world(pos)
        #return world
    
    def get_cursor_position(self):
        xyzv = [0,0,0,0]
        val = self.observer.GetCursorData(xyzv)
        if val: return xyzv[:3]
        else: return None

    def get_pwxyz(self):
        return self.owner.get_plane_widget_xyz()

    def get_pw(self):
        return self.pw

    def get_orientation(self):
        return self.orientation

    def obs_to_world(self, pnt):
        if not self.hasData: return 
        spacing = self.imageData.GetSpacing()
        transform = vtk.vtkTransform()
        transform.Scale(spacing)
        return transform.TransformPoint(pnt)


    
class MainToolbar(MyToolbar):

    toolitems = (
        ('CT Info', 'Load new 3d image', gtk.STOCK_NEW, 'load_image'),
        ('Markers', 'Load markers from file', gtk.STOCK_OPEN, 'load_from'),
        ('Save', 'Save markers', gtk.STOCK_SAVE, 'save'),
        ('Save as ', 'Save markers as new filename', gtk.STOCK_SAVE_AS, 'save_as'),
        (None, None, None, None),
        ('Toggle ', 'Toggle labels display', gtk.STOCK_BOLD, 'toggle_labels'),
        ('Choose', 'Select default marker color', gtk.STOCK_SELECT_COLOR, 'choose_color'),
        (None, None, None, None),
        ('Undo', 'Undo changes', gtk.STOCK_UNDO, 'undo_last'),
        (None, None, None, None),
        ('Properties', 'Set the plane properties', gtk.STOCK_PROPERTIES, 'set_properties'),
        ('Surface', 'Set the surface rendering properties', gtk.STOCK_PROPERTIES, 'show_surf_props'),
        ('Correlation', 'Display Correlations', gtk.STOCK_PROPERTIES, 'show_correlation_props'),
        )


    def __init__(self, owner):
        MyToolbar.__init__(self)

        self.owner = owner

        # set the default color
        da = gtk.DrawingArea()
        cmap = da.get_colormap()
        self.lastColor = cmap.alloc_color(0, 0, 65535)
        # self.build_prop_dialog()
                                    
    def show_surf_props(self, button):
        self.owner.dlgSurf.show()

    def load_correlation_from(fname):
        # opening .mat file with correlation info
        x = scipy.io.loadmat(fname)
        y = x['func_proj']
        print "ch_cmap is " , y.ch_cmap
        print "ch_idx is " , y.ch_idx
        print "ch_names is " , y.ch_names
        print "corr_mat is " , y.corr_mat
        print "disp_data is" , y.disp_data


    def show_correlation_props(self, button):
        dialog = gtk.FileSelection('Choose filename for correlation data')
        dialog.set_filename(shared.get_last_dir())

        dialog.show()
        response = dialog.run()

        if response==gtk.RESPONSE_OK:
            fname = dialog.get_filename()
            dialog.destroy()
            try: EventHandler().load_correlation_from(fname)
            except IOError:
                error_msg(
                    'Could not load correlation from %s' % fname, 
                    )
            
            else:
                shared.set_file_selection(fname)
                self.fileName = fname
        else: dialog.destroy()


    def undo_last(self, button):
        UndoRegistry().undo()

    def toggle_labels(self, button):
        if EventHandler().get_labels_on():                
            EventHandler().set_labels_off()
        else:
            EventHandler().set_labels_on()

    def get_plane_widgets(self):
        pwx = self.owner.pwxyz.pwX
        pwy = self.owner.pwxyz.pwY
        pwz = self.owner.pwxyz.pwZ
        return pwx, pwy, pwz

    def get_markers(self):
        return EventHandler().get_markers()

    def build_prop_dialog(self):
        dlg = gtk.Dialog('Properties')
        #dlg.set_size_request(400,200)

        vbox = dlg.vbox

        frame = gtk.Frame('Opacity')
        frame.show()
        frame.set_border_width(5)
        vbox.pack_start(frame, False, False)


        table = gtk.Table(2,2)
        table.set_homogeneous(False)
        table.show()
        table.set_col_spacings(3)
        table.set_row_spacings(3)
        table.set_border_width(3)
        frame.add(table)

        #EitanP -  start
        frame_size = gtk.Frame('Markers Size')
        frame_size.show()
        frame_size.set_border_width(5)
        vbox.pack_start(frame_size, False, False)

        table_size = gtk.Table(2,2)
        table_size.set_homogeneous(False)
        table_size.show()
        table_size.set_col_spacings(3)
        table_size.set_row_spacings(3)
        table_size.set_border_width(3)
        frame_size.add(table_size)
        #EitanP -  end

        label = gtk.Label('Plane')
        label.show()

        def set_plane_opacity(bar):
            pwx, pwy, pwz = self.get_plane_widgets()
            val = bar.get_value()
            pwx.GetTexturePlaneProperty().SetOpacity(val)
            pwx.GetPlaneProperty().SetOpacity(val)
            pwy.GetTexturePlaneProperty().SetOpacity(val)
            pwy.GetPlaneProperty().SetOpacity(val)
            pwz.GetTexturePlaneProperty().SetOpacity(val) 
            pwz.GetPlaneProperty().SetOpacity(val)
            self.owner.pwxyz.Render()

        scrollbar = gtk.HScrollbar()
        scrollbar.show()
        scrollbar.set_range(0, 1)
        scrollbar.set_value(1)
        scrollbar.connect('value_changed', set_plane_opacity)
        scrollbar.set_size_request(300,20)
        
        table.attach(label, 0, 1, 0, 1)
        table.attach(scrollbar, 1, 2, 0, 1)

        label = gtk.Label('Markers')
        label.show()

        def set_marker_opacity(bar):
            val = bar.get_value()
            for marker in EventHandler().get_markers_as_seq():
                marker.GetProperty().SetOpacity(val)
            
            self.owner.pwxyz.Render()

        scrollbar = gtk.HScrollbar()
        scrollbar.show()
        scrollbar.set_range(0, 1)
        scrollbar.set_value(1)
        scrollbar.connect('value_changed', set_marker_opacity)
        scrollbar.set_size_request(300,20)
        
        table.attach(label,          0, 1, 1, 2)
        table.attach(scrollbar,      1, 2, 1, 2)

        #EitanP -  start
        label = gtk.Label('Markers')
        label.show()
        
        def set_marker_size(bar):
            val = bar.get_value()
            for marker in EventHandler().get_markers_as_seq():
                marker.set_size(val)
            self.owner.pwxyz.Render()            
                        
            self.owner.pwxyz.Render()

        scrollbar_size = gtk.HScrollbar()
        scrollbar_size.show()
        scrollbar_size.set_range(0, 20)
        scrollbar_size.set_value(1)
        scrollbar_size.connect('value_changed', set_marker_size)
        scrollbar_size.set_size_request(300,20)
        table_size.attach(scrollbar_size, 0, 1, 1, 2)
        #EitanP -  end        

        button = gtk.Button('Hide')
        button.show()
        button.set_use_stock(True)
        button.set_label(gtk.STOCK_CANCEL)
        
        def hide(button):
            self.propDialog.hide()
            return True

        button.connect('clicked', hide)
        vbox.pack_start(button, False, False)

        dlg.hide()
        self.propDialog = dlg

    def set_properties(self, *args):
        self.build_prop_dialog()
        self.propDialog.show()
        
    def load_image(self, *args):
        debug = False
        
        if debug:
            reader = vtk.vtkImageReader2()
            reader.SetDataScalarTypeToUnsignedShort()
            reader.SetDataByteOrderToLittleEndian()
            reader.SetFileNameSliceOffset(120)
            reader.SetDataExtent(0, 511, 0, 511, 0, 106)
            reader.SetFilePrefix('/home/jdhunter/seizure/data/ThompsonK/CT/raw/1.2.840.113619.2.55.1.1762864819.1957.1074338393.')
            reader.SetFilePattern( '%s%d.raw')
            reader.SetDataSpacing(25.0/512, 25.0/512, 0.125 )

            reader.Update()
        else:
    
            dlg = widgets['dlgReader']

            response = dlg.run()

            if response == gtk.RESPONSE_OK:
                try: reader = widgets.reader
                except AttributeError: 
                    pars = widgets.get_params()
                    pars = widgets.validate(pars)
                    if pars is None:
                        error_msg('Could not validate the parameters', dlg)
                        return
                    reader = widgets.get_reader(pars)

            dlg.hide()


        imageData = reader.GetOutput()
        imageData.SetSpacing(reader.GetDataSpacing())
        EventHandler().notify('set image data', imageData)
            

    def save_as(self, button):

        def ok_clicked(w):
            fname = dialog.get_filename()
            shared.set_file_selection(fname)
            try: EventHandler().save_markers_as(fname)
            except IOError:
                error_msg('Could not save data to %s' % fname,
                          )
            else:
                self.fileName = fname
                dialog.destroy()
            
        dialog = gtk.FileSelection('Choose filename for marker')
        dialog.set_filename(shared.get_last_dir())
        dialog.ok_button.connect("clicked", ok_clicked)
        dialog.cancel_button.connect("clicked", lambda w: dialog.destroy())
        dialog.show()

    def save(self, button):
        try: self.fileName
        except AttributeError:
            self.save_as(button=None)
        else: EventHandler().save_markers_as(self.fileName)

    def load_from(self, button):

        dialog = gtk.FileSelection('Choose filename for marker info')
        dialog.set_filename(shared.get_last_dir())

        dialog.show()        
        response = dialog.run()
        
        if response==gtk.RESPONSE_OK:
            fname = dialog.get_filename()
            dialog.destroy()
            try: EventHandler().load_markers_from(fname)
            except IOError:
                error_msg(
                    'Could not load markers from %s' % fname, 
                    )
            
            else:
                shared.set_file_selection(fname)
                self.fileName = fname
        else: dialog.destroy()
        

    def choose_color(self, button):
        dialog = gtk.ColorSelectionDialog('Choose default marker color')
            
        colorsel = dialog.colorsel

        
        colorsel.set_previous_color(self.lastColor)
        colorsel.set_current_color(self.lastColor)
        colorsel.set_has_palette(True)
    
        response = dialog.run()
        
        if response == gtk.RESPONSE_OK:
            color = colorsel.get_current_color()
            self.lastColor = color
            EventHandler().set_default_color(self.get_normed_rgb(color))
            
        dialog.destroy()

    def get_normed_rgb(self, c):
        return map(lambda x: x/65535, (c.red, c.green, c.blue))



class InteractorToolbar(gtk.Toolbar):
    def __init__(self):
        gtk.Toolbar.__init__(self)
        
        iconSize = gtk.ICON_SIZE_SMALL_TOOLBAR
        
        self.set_border_width(5)
        self.set_style(gtk.TOOLBAR_BOTH)
        #self.set_orientation(gtk.ORIENTATION_VERTICAL)

    def add_toolbutton1(self, icon_name, tip_text, tip_private, clicked_function, clicked_param1=None):
        iconSize = gtk.ICON_SIZE_SMALL_TOOLBAR
        iconw = gtk.Image()
        iconw.set_from_stock(icon_name, iconSize)
            
        toolitem = gtk.ToolButton()
        toolitem.set_icon_widget(iconw)
        toolitem.show_all()
        toolitem.set_tooltip(self.tooltips1, tip_text, tip_private)
        toolitem.connect("clicked", clicked_function, clicked_param1)
        toolitem.connect("scroll_event", clicked_function)
        self.insert(toolitem, -1)

    def notify(button, event):
        EventHandler().notify(event)

        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_REFRESH, iconSize)
        #buttonInteract = self.append_item(
        #    'Interact',
        #    'Enable mouse rotate/pan/zoom',
        #    'Private',
        #    iconw,
        #    notify,
        #    'mouse1 interact')
        self.add_toolbutton1(gtk.STOCK_REFRESH, 'Enable mouse rotate pan/zoom', 'Private', notify, 'mouse1 interact')


        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_BOLD, iconSize)
        #buttonLabel = self.append_item(
        #    'Label',
        #    'Label clicked markers',
        #    'Private',
        #    iconw,
        #    notify,
        #    'mouse1 label')
        self.add_toolbutton1(gtk.STOCK_BOLD, 'Label clicked markers', 'Private', notify, 'mouse1 label')
        

        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_APPLY, iconSize)
        #buttonSelect = self.append_item(
        #    'Select',
        #    'Select clicked markers',
        #    'Private',
        #    iconw,
        #    notify,
        #    'mouse1 select')
        self.add_toolbutton1(gtk.STOCK_APPLY, 'Select clicked markers', 'Private', notify, 'mouse1 select')


        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_CLEAR, iconSize)
        #buttonColor = self.append_item(
        #    'Color',
        #    'Set marker color',
        #    'Private', 
        #    iconw,
        #    notify,
        #    'mouse1 color')
        self.add_toolbutton1(gtk.STOCK_CLEAR, 'Set marker color', 'Private', notify, 'mouse1 color')

        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_GO_FORWARD, iconSize)
        #buttonColor = self.append_item(
        #    'Move',
        #    'Move markers',
        #    'Private', 
        #    iconw,
        #    notify,
        #    'mouse1 move')
        self.add_toolbutton1(gtk.STOCK_GO_FORWARD, 'Move markers', 'Private', notify, 'mouse1 move')

        #iconw = gtk.Image() # icon widget
        #iconw.set_from_stock(gtk.STOCK_DELETE, iconSize)
        #buttonDelete = self.append_item(
        #    'Delete',
        #    'Delete clicked markers',
        #    'Private', 
        #    iconw,
        #    notify,
        #    'mouse1 delete')
        self.add_toolbutton1(gtk.STOCK_DELETE, 'Delete clicked markers', 'Private', notify, 'mouse1 delete')        

class ObserverToolbar(gtk.Toolbar):
    def __init__(self, pwo):
        'pwo is a PlaneWidgetObserver'
        gtk.Toolbar.__init__(self)

        self.pwo = pwo

        iconSize = gtk.ICON_SIZE_BUTTON
        
        self.set_border_width(5)
        self.set_style(gtk.TOOLBAR_ICONS)
        self.set_orientation(gtk.ORIENTATION_HORIZONTAL)


        def ortho(button):
            pw = pwo.get_pw()
            o = pw.GetCenter()
            xyz = pwo.obs_to_world(o)
            pwxyz = pwo.get_pwxyz()
            pw.SetPlaneOrientation(pwo.get_orientation())
            move_pw_to_point(pw, xyz)
            pwo.update_plane()
            pwo.Render()
            pwxyz.Render()

        iconw = gtk.Image() # icon widget
        iconw.set_from_stock(gtk.STOCK_ADD, iconSize)
        buttonOrtho = self.append_item(
            'Ortho',
            'Restore orthogonality of plane widget',
            'Private',
            iconw,
            ortho)


        def jumpto(button):
            pwxyz = pwo.get_pwxyz()
            pos = pwo.get_cursor_position()
            # get the cursor if it's on, else selection
            if pos is not None:
                xyz = pwo.obs_to_world(pos)
            else:
                selected = EventHandler().get_selected()
                if len(selected) !=1: return
                marker = selected[0]
                xyz = marker.get_center()

            pwxyz.snap_view_to_point(xyz)

        iconw = gtk.Image() # icon widget
        iconw.set_from_stock(gtk.STOCK_JUMP_TO, iconSize)
        buttonJump = self.append_item(
            'Jump to',
            'Move the planes to the point under the cursor or\n' +
            'to the selected marker if only one marker is selected',
            'Private',
            iconw,
            jumpto)

        def coplanar(self):
            numSelected = EventHandler().get_num_selected()
            if numSelected !=3:
                error_msg("You must first select exactly 3 markers",
                          )
                return

            # SetNormal is missing from the 4.2 python API so this is
            # a long winded way of setting the pw to intersect 3
            # selected markers
            m1, m2, m3 = EventHandler().get_selected()

            p1 = m1.get_center()
            p2 = m2.get_center()
            p3 = m3.get_center()
            
            pw = pwo.get_pw()
            planeO = vtk.vtkPlaneSource()
            planeO.SetOrigin(pw.GetOrigin())
            planeO.SetPoint1(pw.GetPoint1())
            planeO.SetPoint2(pw.GetPoint2())
            planeO.Update()

            planeN = vtk.vtkPlaneSource()
            planeN.SetOrigin(p1)
            planeN.SetPoint1(p2)
            planeN.SetPoint2(p3)
            planeN.Update()

            normal = planeN.GetNormal()
            planeO.SetNormal(normal)
            planeO.SetCenter(
                (p1[0] + p2[0] + p3[0])/3,
                (p1[1] + p2[1] + p3[1])/3,
                (p1[2] + p2[2] + p3[2])/3,
                )
            planeO.Update()

            pwxyz = pwo.get_pwxyz()
            pw.SetOrigin(planeO.GetOrigin())
            pw.SetPoint1(planeO.GetPoint1())
            pw.SetPoint2(planeO.GetPoint2())
            pw.UpdatePlacement()
            pwo.update_plane()
            pwo.Render()
            pwxyz.Render()
            
                       
        iconw = gtk.Image() # icon widget
        iconw.set_from_stock(gtk.STOCK_REDO, iconSize)
        buttonPlaneSelected = self.append_item(
            'Set plane',
            'Set the plane to be coplanar with 3 selected electrodes',
            'Private',
            iconw,
            coplanar)

            
class PlaneWidgetsWithObservers(gtk.VBox):
    """
    CLASS: PlaneWidgetsWithObservers
    DESC: controls:
        - PlaneWidgetsXYZ
        - SurfRenderWindow
        - MainToolbar
        - InteractorToolbar
        - SurfRendererProps
    """
    def __init__(self, mainWindow, imageData=None):
        gtk.VBox.__init__(self, spacing=3)
        self.mainWindow = mainWindow
        border = 5
        self.pwxyz = PlaneWidgetsXYZ()
        self.pwxyz.show()


        self.surfRenWin = SurfRenderWindow()
        self.surfRenWin.show()
        
        toolbar = MainToolbar(owner=self)
        toolbar.show()
        toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)        
        self.pack_start(toolbar, False, False)
        self.mainToolbar = toolbar
        
        toolbarInteractor = InteractorToolbar()
        toolbarInteractor.show()
        toolbarInteractor.set_orientation(gtk.ORIENTATION_VERTICAL)        

        self.dlgSurf = SurfRendererProps(self.surfRenWin, self.pwxyz)

        vboxTools = gtk.VBox()
        vboxTools.show()
        
        hbox = gtk.HBox(spacing=border)
        #hbox.set_border_width(border)
        hbox.show()


        vboxTools.pack_start(toolbarInteractor, False, False)

        hbox.pack_start(vboxTools, False, False)
        self.pack_start(hbox, True, True)


        vbox = gtk.VBox(spacing=border)
        #vbox.set_border_width(border)
        vbox.show()
        hbox.pack_start(vbox, True, True)


        hboxUpper = gtk.HBox(spacing=border)
        hboxUpper.show()
        hboxUpper.pack_start(self.pwxyz, True, True)
        hboxUpper.pack_start(self.surfRenWin, True, True)
        vbox.pack_start(hboxUpper, True, True)

        pwx, pwy, pwz = self.pwxyz.get_plane_widgets_xyz()


        hbox = gtk.HBox(spacing=border)
        #hbox.set_border_width(border)
        hbox.show()
        vbox.pack_start(hbox, True, True)

        vboxObs = gtk.VBox()
        vboxObs.show()
        self.observerX = PlaneWidgetObserver(pwx, owner=self, orientation=0)
        self.observerX.show()

        vboxObs.pack_start(self.observerX, True, True)
        toolbarX = ObserverToolbar(self.observerX)
        toolbarX.show()
        vboxObs.pack_start(toolbarX, False, False)
        hbox.pack_start(vboxObs, True, True)

        vboxObs = gtk.VBox()
        vboxObs.show()
        self.observerY = PlaneWidgetObserver(pwy, owner=self, orientation=1)
        self.observerY.show()
        vboxObs.pack_start(self.observerY, True, True)
        toolbarY = ObserverToolbar(self.observerY)
        toolbarY.show()
        vboxObs.pack_start(toolbarY, False, False)
        hbox.pack_start(vboxObs, True, True)

        vboxObs = gtk.VBox()
        vboxObs.show()
        self.observerZ = PlaneWidgetObserver(pwz, owner=self, orientation=2)
        self.observerZ.show()
        vboxObs.pack_start(self.observerZ, True, True)
        toolbarZ = ObserverToolbar(self.observerZ)
        toolbarZ.show()



        vboxObs.pack_start(toolbarZ, False, False)
        hbox.pack_start(vboxObs, True, True)

        #self.pwxyz.set_size_request(450, 150)
        #self.observerX.set_size_request(150, 150)
        #self.observerY.set_size_request(150, 150)
        #self.observerZ.set_size_request(150, 150)

        # render all observers on interaction events with plane
        # widgets to allow common window level settings
        pwx.AddObserver('InteractionEvent', self.render_observers)
        pwy.AddObserver('InteractionEvent', self.render_observers)
        pwz.AddObserver('InteractionEvent', self.render_observers)
        #self.set_image_data(imageData)

        self.observerX.observer.AddObserver('InteractionEvent', self.dlgSurf.interaction_event)
        self.observerY.observer.AddObserver('InteractionEvent', self.dlgSurf.interaction_event)
        self.observerZ.observer.AddObserver('InteractionEvent', self.dlgSurf.interaction_event)

    def set_image_data(self, imageData):
        if imageData is None: return 
        self.pwxyz.set_image_data(imageData)
        self.surfRenWin.set_image_data(imageData)
        self.observerX.set_image_data(imageData)
        self.observerY.set_image_data(imageData)
        self.observerZ.set_image_data(imageData)
        
        
    def get_observer_x(self):
        return self.observerX

    def get_observer_y(self):
        return self.observerY

    def get_observer_z(self):
        return self.observerZ

    def get_plane_widget_x(self):
        return self.pwxyz.get_plane_widget_x()

    def get_plane_widget_y(self):
        return self.pwxyz.get_plane_widget_y()

    def get_plane_widget_z(self):
        return self.pwxyz.get_plane_widget_z()

    def get_plane_widget_xyz(self):
        return self.pwxyz


    def render_observers(self, *args):
        #print 'rendering all'
        self.surfRenWin.Render()        
        self.observerX.Render()
        self.observerY.Render()
        self.observerZ.Render()


