# <pep8 compliant>

import importlib

import bpy

from . import base
from . import draw
from .. import utils
from ... import poll
from ... import constants
from ... import extend_bpy_types

# Contains currently running modal operators
modal_ops = []

if "_rc" in locals():  # In case of module reloading
    for operator in modal_ops:
        try:
            # Cancellation of the previous running operators
            operator.cancel(bpy.context)
        except AttributeError:
            print("AttributeError. Missing cancel method", operator)
        except ReferenceError:
            import traceback
            print(traceback.format_exc())

    importlib.reload(base)
    importlib.reload(draw)
    importlib.reload(utils)
    importlib.reload(poll)
    importlib.reload(constants)
    importlib.reload(extend_bpy_types)

_rc = None


# The update period of the main modal operators
LISTEN_TIME_STEP = 1 / 4
TIME_STEP = 1 / 60

# CPP_OT_listener methods


def listener_cancel(self, context):
    if self in modal_ops:
        modal_ops.remove(self)

    wm = context.window_manager
    wm.event_timer_remove(self.timer)


def listener_invoke(self, context, event):
    if self not in modal_ops:
        modal_ops.append(self)

    wm = context.window_manager
    self.timer = wm.event_timer_add(
        time_step=LISTEN_TIME_STEP, window=context.window)
    wm.modal_handler_add(self)
    return {'RUNNING_MODAL'}


def listener_modal(self, context, event):
    wm = context.window_manager
    if wm.cpp_running:
        self.cancel(context)
        return {'FINISHED'}

    if event.type == 'TIMER':
        if not wm.cpp_running:
            if poll.full_poll(context):
                wm.cpp_running = True
                wm.cpp_suspended = False
                bpy.ops.cpp.camera_projection_painter('INVOKE_DEFAULT')

    return {'PASS_THROUGH'}


# CPP_OT_camera_projection_painter methods

def operator_invoke(self, context, event):
    scene = context.scene

    is_cameras_visible = False
    for ob in context.visible_objects:
        if ob.type == 'CAMERA':
            is_cameras_visible = True
    if not is_cameras_visible:
        return {'CANCELLED'}

    base.set_properties_defaults(self)
    base.validate_cameras_data_settings(context)
    base.setup_basis_uv_layer(context)

    scene.cpp.ensure_objects_initial_hide_viewport(context)
    scene.cpp.cameras_hide_set(state=True)
    bpy.ops.ed.flush_edits()

    ob = context.image_paint_object

    self.mesh_batch = draw.mesh_preview.get_object_batch(context, ob)
    self.axes_batch = draw.cameras.get_axes_batch()
    self.camera_batch, self.image_rect_batch = draw.cameras.get_camera_batches()
    draw.add_draw_handlers(self, context)

    wm = context.window_manager
    self.timer = wm.event_timer_add(time_step=TIME_STEP, window=context.window)
    wm.modal_handler_add(self)

    if self not in modal_ops:
        modal_ops.append(self)

    return {'RUNNING_MODAL'}


def operator_cancel(self, context):
    if self in modal_ops:
        modal_ops.remove(self)

    scene = context.scene
    ob = context.active_object
    wm = context.window_manager

    wm.event_timer_remove(self.timer)

    draw.cameras.clear_image_previews()
    utils.warnings.clear_image_loading_order()
    extend_bpy_types.image.clear_static_size_cache()

    draw.remove_draw_handlers(self)
    base.remove_uv_layer(ob)
    scene.cpp.cameras_hide_set(state=False)

    wm.cpp_running = False
    wm.cpp_suspended = False

    base.set_properties_defaults(self)


def operator_modal(self, context, event):
    wm = context.window_manager

    if not poll.full_poll(context):
        self.cancel(context)
        bpy.ops.cpp.listener('INVOKE_DEFAULT')
        return {'FINISHED'}

    if wm.cpp_suspended:
        return {'PASS_THROUGH'}

    scene = context.scene

    # update viewports on mouse movements
    if event.type == 'MOUSEMOVE':
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    # deal with hotkey adjust brush radius/strength
    if event.type == 'F' and event.value == 'PRESS':
        self.suspended_mouse = True
        self.suspended_brush = False
    elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        self.suspended_mouse = False
        self.suspended_brush = True
    elif event.value == 'RELEASE':
        self.suspended_mouse = False
        self.suspended_brush = False

    if not self.suspended_mouse:
        wm.cpp_mouse_pos = event.mouse_x, event.mouse_y

    ob = context.image_paint_object
    image_paint = scene.tool_settings.image_paint
    clone_image = image_paint.clone_image
    canvas = image_paint.canvas
    material = ob.active_material

    # Manully call image.buffers_free(). BF does't do this so Blender often crashes
    # Also, it checks if image preview generated
    draw.cameras.check_image_previews(self, context)

    if scene.cpp.use_projection_preview:
        draw.mesh_preview.update_brush_texture_bindcode(self, context)

    if scene.cpp.use_auto_set_camera:
        rv3d = utils.screen.get_hovered_region_3d(context, wm.cpp_mouse_pos)
        utils.cameras.set_camera_by_view(context, rv3d, wm.cpp_mouse_pos)

    if scene.cpp.use_auto_set_image:
        utils.cameras.set_clone_image_from_camera_data(context)

    if scene.cpp.use_bind_canvas_diffuse and material:
        diffuse_node = utils.material.search_diffuse_node(material)
        if diffuse_node:
            if self.canvas_updated(canvas):
                if hasattr(canvas, "cpp") and (not canvas.cpp.valid):
                    canvas = None
                result = utils.material.set_canvas_to_material_diffuse(material, canvas)
                if result == -1:
                    self.report(type={'INFO'}, message="Diffuse texture set from canvas")
                else:
                    self.report(type={'WARNING'}, message="Failed to set diffuse texture from canvas!")
                self.report
            elif self.diffuse_updated(diffuse_node.image):
                result = utils.material.set_material_diffuse_to_canvas(image_paint, material)
                if result == -1:
                    self.report(type={'INFO'}, message="Canvas set of diffuse texture")
                elif result == 1:
                    self.report(type={'WARNING'}, message="The material has no active output!")
                elif result == 2:
                    self.report(type={'WARNING'}, message="Invalid image found in nodes!")
                elif result == 3:
                    self.report(type={'WARNING'}, message="Image not found!")

    camera_ob = scene.camera
    camera = camera_ob.data

    check_tuple = (
        camera_ob, camera, clone_image,  # Base properties
        camera.lens,
        camera.shift_x,
        camera.shift_y,
        camera.sensor_fit,
        camera.cpp.use_calibration,  # Calibration properties
        camera.cpp.calibration_principal_point[:],
        camera.cpp.calibration_skew,
        camera.cpp.calibration_aspect_ratio,
        camera.cpp.lens_distortion_radial_1,
        camera.cpp.lens_distortion_radial_2,
        camera.cpp.lens_distortion_radial_3,
        camera.cpp.lens_distortion_tangential_1,
        camera.cpp.lens_distortion_tangential_2,
    )

    if self.check_data_updated(check_tuple):
        self.full_draw = True

    if event.type not in ('TIMER', 'TIMER_REPORT'):
        if self.data_updated(check_tuple):
            base.setup_basis_uv_layer(context)
            if scene.camera.data.cpp.use_calibration:
                base.deform_uv_layer(self, context)
            self.full_draw = False

    return {'PASS_THROUGH'}
