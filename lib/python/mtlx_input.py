import os
import time
import logging

import imath
import IECore
import Gaffer
import GafferScene
import GafferArnold

import MaterialX as mx


# Initializes the logger
logging.basicConfig(level=logging.INFO, format="%(levelname)s : [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def fix_str(name):
    """
    Replace symbols with '_' strings
    @param name: str
    @return: str
    """
    characters = ":/"

    for char in characters:
        name = name.replace(char, "_")

    return str(name)


class MtlXInputSerialiser(Gaffer.NodeSerialiser):
    """
    MtlXInput Serializer
    """
    def childNeedsSerialisation(self, child, serialisation):
        """
        Implementation of native method
        @param child: MtlXInput
        @param serialisation: Gaffer.Serialisation
        @return: 
        """
        if isinstance(child, Gaffer.Node):
            return True

        return Gaffer.NodeSerialiser.childNeedsSerialisation(self, child, serialisation)

    def childNeedsConstruction(self, child, serialisation):
        """
        Implementation of native method
        @param child: MtlXInput
        @param serialisation: Gaffer.Serialisation
        @return:
        """
        if isinstance(child, Gaffer.Node):
            return True

        return Gaffer.NodeSerialiser.childNeedsConstruction(self, child, serialisation)


class MtlXInput(GafferScene.SceneNode):
    """
    MaterialX Reader Node
    """
    def __init__(self, name="MtlXInput"):
        """
        @param name: str
        """
        GafferScene.SceneNode.__init__(self, name)

        # Status string
        self.status = str()

        # MaterialX document object
        self.mtlx_doc = None

        self["mtlXPath"] = Gaffer.StringPlug()
        self["refresh"] = Gaffer.IntPlug()
        self["mtlXLook"] = Gaffer.IntPlug()
        self["resolved"] = Gaffer.StringPlug()
        self["status"] = Gaffer.StringPlug("status", Gaffer.Plug.Direction.Out)

        self["applyMaterials"] = Gaffer.BoolPlug(defaultValue=True)
        self["applyAssignments"] = Gaffer.BoolPlug(defaultValue=True)
        self["applyAttributes"] = Gaffer.BoolPlug(defaultValue=True)

        self["in"] = GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In, flags=Gaffer.Plug.Flags.Default)
        self["out"] = GafferScene.ScenePlug("out", Gaffer.Plug.Direction.Out)
        self["out"].setInput(self["in"])

        self.plugSetSignal().connect(self.plug_set, scoped=False)

    def hash(self, output, context, h):
        """
        Implementation of native method
        @param output: Gaffer.Plug
        @param context: Gaffer.Context
        @param h: IECore.MurmurHash
        @return: None
        """
        if self["mtlXPath"].hash() != self["resolved"].hash():

            if self.valid_mtlx():
                self.clear_existing_data()
                self.load_mtlx()
            else:
                self["out"].setInput(self["in"])

            self["resolved"].setValue(self["mtlXPath"].getValue())

        h.append(self['mtlXPath'].hash())
        h.append(self["mtlXLook"].hash())
        h.append(self['refresh'].hash())

    def hashCachePolicy(self, output):
        """
        Implementation of native method
        @param output: Gaffer.Plug
        @return: Gaffer.ValuePlug.CachePolicy
        """
        return Gaffer.ValuePlug.CachePolicy.Uncached

    def compute(self, output, context):
        """
        Implementation of native method
        @param output: Gaffer.Plug
        @param context: Gaffer.Context
        @return:
        """
        if output.getName() == "status":
            output.setValue(self.status)

    def plug_set(self, plug):
        """
        Sets plug value
        @param plug: Gaffer.Plug
        @return: None
        """
        if plug.getName() == "refresh":

            self["resolved"].setValue("")

        elif plug.getName() == "mtlXLook":

            self.setup_assignments(plug.getValue())

    def valid_mtlx(self):
        """
        Validates MaterialX file path
        @return: bool
        """
        self.mtlx_doc = mx.createDocument()

        try:
            mx.readFromXmlFile(self.mtlx_doc, self["mtlXPath"].getValue())
            return True
        except mx.ExceptionFileMissing as err:
            self.status = str(err)

    def load_mtlx(self):
        """
        Loads MaterialX to the graph
        @return: None
        """
        x = time.time()

        if self["applyMaterials"].getValue():
            self.setup_materials()

        if self["applyAssignments"].getValue():
            self.setup_assignments()

        if self["applyAttributes"].getValue():
            self.setup_attributes()

        # Sets status
        self.status = "%d Materials loaded in %.2f seconds" % (len(self.material_list()), time.time() - x)

    def material_list(self):
        """
        Gets Materials list
        @return: list
        """
        return [i for i in self.children() if i.isInstanceOf(Gaffer.Box)]

    def attribute_list(self):
        """
        Gets Attribute list
        @return: list
        """
        return [i for i in self.children() if i.isInstanceOf(GafferArnold.ArnoldAttributes)]

    def path_filter_list(self):
        """
        Gets Attribute list
        @return: list
        """
        return [i for i in self.children() if i.isInstanceOf(GafferScene.PathFilter)]

    def clear_existing_data(self):
        """
        Removes already existing data
        """
        for material in self.material_list():
            self.removeChild(material)

        for attribute in self.attribute_list():
            self.removeChild(attribute)

        for path_filter in self.path_filter_list():
            self.removeChild(path_filter)

    def setup_materials(self):
        """
        Creates Materials, Shaders and sets Input values
        @return: None
        """
        x = time.time()
        shader_count = 0

        # Creates Materials
        for material in self.mtlx_doc.getMaterials():

            material_name = fix_str(material.getName())

            box_in = Gaffer.BoxIn()
            box_out = Gaffer.BoxOut()
            material_box = Gaffer.Box(material_name)

            # Creates shader reference nodes
            for shader_ref in material.getShaderRefs():

                shader_name = fix_str(shader_ref.getName())

                shader = GafferArnold.ArnoldShader(shader_name)
                shader.loadShader(shader_ref.getNodeString())

                shader_assignment = GafferScene.ShaderAssignment()
                shader_assignment['shader'].setInput(shader["out"])

                box_in.setup(shader_assignment["in"])
                box_out.setup(shader_assignment["out"])

                shader_assignment["in"].setInput(box_in["out"])
                box_out["in"].setInput(shader_assignment["out"])

                path_filter = GafferScene.PathFilter()
                shader_assignment['filter'].setInput(path_filter["out"])

                # Displacement Shader
                if shader_ref.getAttribute("context") == "displacementshader":
                    dsp_shader =  GafferArnold.ArnoldDisplacement()
                    shader_assignment['shader'].setInput(dsp_shader["out"])
                    dsp_shader['map'].setInput(shader["out"])
                    material_box.addChild(dsp_shader)

                material_box.addChild(shader)
                material_box.addChild(box_in)
                material_box.addChild(box_out)
                material_box.addChild(path_filter)
                material_box.addChild(shader_assignment)

                box_in.setupPromotedPlug()
                box_out.setupPromotedPlug()

                material_list = self.material_list()

                if material_list:
                    if material_box != material_list[-1]:
                        material_box["in"].setInput(material_list[-1]["out"])

                    material_list[0]["in"].setInput(self["in"])
                    self["out"].setInput(material_box["out"])

                self.addChild(material_box)

                # Sets shader reference input values
                for bind_input in shader_ref.getBindInputs():
                    value = bind_input.getValue()

                    if value is not None:

                        shader_parm = shader['parameters']
                        input_name = str(bind_input.getName())

                        if input_name in shader_parm:
                            self.set_input_value(shader_parm[input_name], value)

                # Create shader nodes
                for graph in shader_ref.traverseGraph(material):

                    node = graph.getUpstreamElement()

                    if node.isA(mx.Node):

                        shader_list = [i.getName() for i in material_box.children()
                                   if isinstance(i, GafferArnold.ArnoldShader)]

                        node_name = fix_str(node.getName())

                        if node_name not in shader_list:

                            shader = GafferArnold.ArnoldShader(node_name)
                            shader.loadShader(node.getCategory())
                            material_box.addChild(shader)
                            shader_count += 1

                            # Sets shader input values
                            for input_parm in node.getInputs():

                                input_name = str(input_parm.getName())

                                if shader is not None:

                                    shader_parm = shader['parameters']

                                    if input_name in shader_parm:

                                        value = input_parm.getValue()

                                        if value is not None:
                                            self.set_input_value(shader_parm[input_name], value)
        # Sets Connections
        for material in self.mtlx_doc.getMaterials():

            material_box = self[fix_str(material.getName())]

            for shader_ref in material.getShaderRefs():

                shader_name = fix_str(shader_ref.getName())
                shader = material_box[shader_name]
                shader_parm = shader['parameters']

                for bind_input in shader_ref.getBindInputs():

                    input_name = str(bind_input.getName())
                    output = bind_input.getConnectedOutput()

                    if output is not None:

                        node_name = fix_str(output.getNodeName())

                        if node_name:
                            if input_name in shader_parm:
                                self.set_input_connection(shader_parm[input_name],
                                                          material_box[node_name]["out"])

                for graph in shader_ref.traverseGraph():

                    shader_node = graph.getUpstreamElement()

                    if shader_node.isA(mx.Node):

                        shader_name = fix_str(shader_node.getName())
                        shader = material_box[shader_name]
                        shader_parm = shader['parameters']

                        for input_parm in shader_node.getInputs():

                            input_name = str(input_parm.getName())
                            node_name = fix_str(input_parm.getNodeName())

                            if node_name:
                                if input_name in shader_parm:
                                    self.set_input_connection(shader_parm[input_name],
                                                              material_box[node_name]["out"])

        logger.info("%s Loaded %d shaders in %.2f seconds" % (self.getName(), shader_count, time.time() - x))

    def setup_assignments(self, look_idx=0):
        """
        Creates Assignments and Looks
        @return: None
        """
        x = time.time()
        assign_count = 0

        self["mtlXLook"].setValue(look_idx)

        if self.mtlx_doc is None:
            if not self.valid_mtlx():
                return

        # Sets Assignments
        for idx, look in enumerate(self.mtlx_doc.getLooks()):

            look_name = str(look.getName())
            Gaffer.Metadata.registerPlugValue(self["mtlXLook"], "preset:" + look_name, idx)

            if look_idx == idx:

                material_list = self.material_list()

                # Reset assignments
                for mat in material_list:
                    mat["PathFilter"]["paths"].setValue(IECore.StringVectorData([]))

                # Assigns Materials
                for mat_assign in look.getMaterialAssigns():

                    mat_assign_name = fix_str(mat_assign.getReferencedMaterial().getName())

                    for mat in material_list:

                        if mat_assign_name == mat.getName():

                            value = mat["PathFilter"]["paths"].getValue()

                            if value is not None:

                                geom_name = mat_assign.getGeom()
                                split_name = geom_name.split("/")

                                if split_name:
                                    value.append(geom_name.replace(split_name[-1], ""))
                                    mat["PathFilter"]["paths"].setValue(value)

                                    assign_count += 1

        logger.info("%s Loaded %d assignments in %.2f seconds" % (self.getName(), assign_count, time.time() - x))

    def setup_attributes(self, look_idx=0):
        x = time.time()
        attribute_count = 0

        self["mtlXLook"].setValue(look_idx)

        if self.mtlx_doc is None:
            if not self.valid_mtlx():
                return

        # Sets Attributes
        for idx, look in enumerate(self.mtlx_doc.getLooks()):

            if look_idx == idx:

                material_list = self.material_list()

                # Assigns Visibility attributes
                attribute_assignment = None
                for idx, visibility in enumerate(look.getVisibilities()):

                    attrib_list = self.attribute_list()

                    if idx % 8 == 0:

                        attribute_assignment = GafferArnold.ArnoldAttributes()
                        path_filter = GafferScene.PathFilter()

                        attribute_assignment['filter'].setInput(path_filter["out"])

                        if attrib_list:
                            attribute_assignment["in"].setInput(attrib_list[-1]["out"])
                        else:

                            if material_list:
                                attribute_assignment["in"].setInput(material_list[-1]["out"])
                            else:
                                attribute_assignment["in"].setInput(self["in"])

                        geom_name = visibility.getGeom()
                        path_filter["paths"].setValue(IECore.StringVectorData([geom_name]))

                        self.addChild(attribute_assignment)
                        self.addChild(path_filter)

                        attribute_count += 1

                    vis_type = visibility.getVisibilityType()
                    is_visible = visibility.getVisible()
                    attributes = attribute_assignment["attributes"]

                    if vis_type == "camera":
                        attributes["cameraVisibility"]["enabled"].setValue(True)
                        attributes["cameraVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "shadow":
                        attributes["shadowVisibility"]["enabled"].setValue(True)
                        attributes["shadowVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "diffuse_transmit":
                        attributes["diffuseTransmissionVisibility"]["enabled"].setValue(True)
                        attributes["diffuseTransmissionVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "specular_transmit":
                        attributes["specularTransmissionVisibility"]["enabled"].setValue(True)
                        attributes["specularTransmissionVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "volume":
                        attributes["volumeVisibility"]["enabled"].setValue(True)
                        attributes["volumeVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "diffuse_reflect":
                        attributes["diffuseReflectionVisibility"]["enabled"].setValue(True)
                        attributes["diffuseReflectionVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "specular_reflect":
                        attributes["specularReflectionVisibility"]["enabled"].setValue(True)
                        attributes["specularReflectionVisibility"]["value"].setValue(is_visible)

                    elif vis_type == "subsurface":
                        attributes["subsurfaceVisibility"]["enabled"].setValue(True)
                        attributes["subsurfaceVisibility"]["value"].setValue(is_visible)

                if attribute_assignment is not None:
                    self["out"].setInput(attribute_assignment["out"])

        logger.info("%s Loaded %d attributes in %.2f seconds" % (self.getName(), attribute_count, time.time() - x))

    @staticmethod
    def set_input_value(input_plug, value):
        """
        Sets input plug value
        @param input_plug: Gaffer.Plug
        @param value:
        @return: None
        """
        assert(input_plug.isInstanceOf(Gaffer.Plug))

        try:
            if input_plug.isInstanceOf(Gaffer.Color3fPlug):
                input_plug.setValue(imath.Color3f(value[0], value[1], value[2]))

            elif input_plug.isInstanceOf(Gaffer.Color4fPlug):
                input_plug.setValue(imath.Color4f(value[0], value[1], value[2], value[3]))

            elif input_plug.isInstanceOf(Gaffer.V3fPlug):
                input_plug.setValue(imath.V3f(value[0], value[1], value[2]))

            else:
                input_plug.setValue(value)

        except Exception as err:
            logger.warning("Failed to set value '%s' -> '%s'\n%s" % (input_plug, value, err))

    @staticmethod
    def set_input_connection(input_plug, output_plug):
        """
        Sets input connection
        @param input_plug: Gaffer.Plug
        @param output_plug: Gaffer.Plug
        @return: None
        """
        assert (input_plug.isInstanceOf(Gaffer.Plug))
        assert (output_plug.isInstanceOf(Gaffer.Plug))

        try:
            if (output_plug.isInstanceOf(Gaffer.FloatPlug) or
                    output_plug.isInstanceOf(Gaffer.IntPlug)) and \
                    (input_plug.isInstanceOf(Gaffer.Color3fPlug) or
                         input_plug.isInstanceOf(Gaffer.Color4fPlug)):

                ch_in = input_plug.keys()[0]
                input_plug[ch_in].setInput(output_plug)

            elif (input_plug.isInstanceOf(Gaffer.FloatPlug) or
                      input_plug.isInstanceOf(Gaffer.IntPlug)) and \
                    (output_plug.isInstanceOf(Gaffer.Color3fPlug) or
                         output_plug.isInstanceOf(Gaffer.Color4fPlug)):

                ch_out = output_plug.keys()[0]
                input_plug.setInput(output_plug[ch_out])

            elif (input_plug.isInstanceOf(Gaffer.Color4fPlug) and
                      output_plug.isInstanceOf(Gaffer.Color3fPlug)) or \
                    (input_plug.isInstanceOf(Gaffer.Color3fPlug) and
                         output_plug.isInstanceOf(Gaffer.Color4fPlug)) or \
                    (input_plug.isInstanceOf(Gaffer.Color4fPlug) and
                         output_plug.isInstanceOf(Gaffer.V3fPlug)):

                input_plug[input_plug.keys()[0]].setInput(output_plug[output_plug.keys()[0]])
                input_plug[input_plug.keys()[1]].setInput(output_plug[output_plug.keys()[1]])
                input_plug[input_plug.keys()[2]].setInput(output_plug[output_plug.keys()[2]])

            elif (output_plug.isInstanceOf(Gaffer.FloatPlug) or
                    output_plug.isInstanceOf(Gaffer.IntPlug)) and input_plug.isInstanceOf(Gaffer.V3fPlug):

                ch_in = input_plug.keys()[0]
                input_plug[ch_in].setInput(output_plug)

            elif (input_plug.isInstanceOf(Gaffer.FloatPlug) or
                      input_plug.isInstanceOf(Gaffer.IntPlug)) and output_plug.isInstanceOf(Gaffer.V3fPlug):

                ch_out = output_plug.keys()[0]
                input_plug.setInput(output_plug[ch_out])

            else:
                input_plug.setInput(output_plug)

        except Exception as err:
            logger.warning("Failed to connect '%s' -> '%s'\n%s" % (output_plug, input_plug, err))


IECore.registerRunTimeTyped(MtlXInput, typeName="mtlx_input.MtlXInput")


Gaffer.Metadata.registerNode(

    MtlXInput,
    "description",

    """
    MaterialX Reader
    """,

    "icon", os.path.join(os.getenv('GAFFER_MATERIAL_X_ROOT'), "share/icon/MaterialXLogoSmallA.png"),
    "graphEditor:childrenViewable", True,

    plugs = { "mtlXPath" : ["description",

                            """
                            MaterialX File Path
                            """,

                            "plugValueWidget:type", "GafferUI.FileSystemPathPlugValueWidget",
                            "path:leaf", True,
                            "path:valid", True,
                            "nodule:type", "GafferUI::StandardNodule",
                            "fileSystemPath:extensions", "mtlx",
                            "fileSystemPath:extensionsLabel", "Show only .mtlx files",
                            ],

		       "refresh" : [ "description",

                            """
                            May be incremented to force a reload if the file has
                            changed on disk - otherwise old contents may still
                            be loaded via Gaffer's cache.
                            """,

                            "plugValueWidget:type", "GafferUI.RefreshPlugValueWidget",
                            "layout:label", "",
                            "layout:accessory", True,
                             ],

		       "mtlXLook" : ["description",

                             """
                             The Look
                             """,

                            "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
                             ],

              "resolved" : ["description",

                            """
                            Hidden plug
                            """,

                            "plugValueWidget:type", ""
                            ]
            }
    )


Gaffer.Serialisation.registerSerialiser(MtlXInput, MtlXInputSerialiser())


def init(application):
    import GafferUI
    node_menu = GafferUI.NodeMenu.acquire(application)
    node_menu.append("/RSP/MtlXInput", lambda: MtlXInput(), searchText="MtlXInput")
