import uuid
from datetime import date
from collections import defaultdict
import numpy as np
import dotbimpy
import bpy
import bmesh
import re


def triangulate_mesh(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()


def convert_blender_mesh_to_dotbim(blender_mesh, index, transform_matrix, vertex_colors_layer):
    vertices = np.empty(shape=len(blender_mesh.vertices) * 3, dtype=float)
    blender_mesh.vertices.foreach_get("co", vertices)
    scale = transform_matrix.to_scale()
    for i in range(3):
        vertices[i::3] *= scale[i]

    triangulate_mesh(blender_mesh)
    faces = np.empty(shape=len(blender_mesh.polygons) * 3, dtype=int)
    blender_mesh.polygons.foreach_get("vertices", faces)

    face_colors = get_vertex_colors_map(blender_mesh, vertex_colors_layer) if vertex_colors_layer else None

    return (dotbimpy.Mesh(mesh_id=index, coordinates=vertices.tolist(), indices=faces.tolist()), face_colors)


def get_all_ui_props(obj):
    items = obj.items()
    rna_properties = {prop.identifier for prop in obj.bl_rna.properties if prop.is_runtime}
    for k, v in items:
        if k in rna_properties:
            continue
        yield (k, v)


def get_vertex_colors_map(mesh, layer_name):
    if not mesh.vertex_colors:
        return None

    color_layer = mesh.vertex_colors[layer_name]
    face_colors = np.empty(shape=len(color_layer.data) * 4, dtype=float)
    color_layer.data.foreach_get("color", face_colors)
    face_colors = face_colors.reshape(-1, 4)[0::3].flatten()  # Remy F https://stackoverflow.com/a/61140462/7092409
    return face_colors


def export_objects(objs, filepath, author="John Doe", type_from="NAME", vertex_colors_layer="Col"):
    meshes = []
    elements = []

    data_users = defaultdict(list)
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for obj in objs:
        if obj.type not in ("MESH", "CURVE", "FONT", "META", "SURFACE"):
            continue
        if obj.modifiers or obj.scale[0] != 1 or obj.scale[1] != 1 or obj.scale[2] != 1:
            data_users[obj].append(obj)
        else:
            data_users[obj.data].append(obj)
    for i, users in enumerate(data_users.values()):
        base_obj = users[0]
        mesh_blender = base_obj.evaluated_get(depsgraph).to_mesh()  # Apply visual modifiers, transforms, etc.
        transform_matrix = base_obj.matrix_world
        mesh_dotbim, face_colors = convert_blender_mesh_to_dotbim(
            mesh_blender,
            i,
            transform_matrix,
            vertex_colors_layer,
        )
        meshes.append(mesh_dotbim)

        for obj in users:
            r, g, b, a = obj.color
            color = dotbimpy.Color(r=int(r * 255), g=int(g * 255), b=int(b * 255), a=int(a * 255))

            guid = str(uuid.uuid4())

            info = {"Name": obj.name}
            for custom_prop_name, custom_prop_value in get_all_ui_props(obj):
                info[custom_prop_name] = str(custom_prop_value)

            matrix_world = obj.matrix_world
            obj_trans = matrix_world.to_translation()
            obj_quat = matrix_world.to_quaternion()

            rotation = dotbimpy.Rotation(qx=obj_quat.x, qy=obj_quat.y, qz=obj_quat.z, qw=obj_quat.w)

            if type_from == "COLLECTION":
                name = obj.users_collection[0].name
            else:
                name = obj.name
                # Strip the trailing ".xxx" numbers from the object name
                search = re.search("\.[0-9]+$", name)
                if search:
                    name = name[0 : search.start()]

            vector = dotbimpy.Vector(x=obj_trans.x, y=obj_trans.y, z=obj_trans.z)
            element = dotbimpy.Element(
                mesh_id=i,
                vector=vector,
                guid=guid,
                info=info,
                rotation=rotation,
                type=name,
                color=color,
                face_colors=face_colors,
            )

            elements.append(element)

    file_info = {"Author": author, "Date": date.today().strftime("%d.%m.%Y")}
    file = dotbimpy.File("1.0.0", meshes=meshes, elements=elements, info=file_info)
    file.save(filepath)


if __name__ == "__main__":
    objects = bpy.context.selected_objects
    export_objects(objs=objects, filepath=r"House.bim")
