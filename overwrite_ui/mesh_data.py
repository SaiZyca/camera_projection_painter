# <pep8 compliant>

import importlib

import bpy

from . import constants
from .. import constants as addon_constants
from .. import icons
from .. import operators

if "_rc" in locals():  # In case of module reloading
    importlib.reload(constants)
    importlib.reload(addon_constants)
    importlib.reload(icons)
    importlib.reload(operators)

_rc = None


class MESH_UL_uvmaps:
    def draw_item(self, _context, layout, _data, item, icon, _active_data, _active_propname, _index):

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            # ----------------------------\
            if item.name == addon_constants.TEMP_DATA_NAME:
                row = layout.row(align=True)
                row.emboss = 'NONE'
                row.operator(
                    operator=operators.CPP_OT_info.bl_idname,
                    text="Camera Paint",
                    icon_value=icons.get_icon_id("overwriten")
                ).text = constants.OVERWRITE_UI_MESSAGE
                return
            # ----------------------------/
            layout.prop(item, "name", text="", emboss=False, icon='GROUP_UVS')
            icon = 'RESTRICT_RENDER_OFF' if item.active_render else 'RESTRICT_RENDER_ON'
            layout.prop(item, "active_render", text="",
                        icon=icon, emboss=False)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)


class DATA_PT_uv_texture:
    def draw(self, context):
        layout = self.layout

        me = context.mesh

        row = layout.row()
        col = row.column()

        col.template_list("MESH_UL_uvmaps", "uvmaps", me,
                          "uv_layers", me.uv_layers, "active_index", rows=2)

        col = row.column(align=True)
        col.operator("mesh.uv_texture_add", icon='ADD', text="")

        # ----------------------------/
        scol = col.column(align=True)
        enable = True
        uv_layers = me.uv_layers
        if uv_layers.active:
            if uv_layers.active.name == addon_constants.TEMP_DATA_NAME:
                enable = False
        scol.enabled = enable
        scol.operator("mesh.uv_texture_remove", icon='REMOVE', text="")
        # ----------------------------
