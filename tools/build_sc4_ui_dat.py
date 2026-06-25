"""Build the dependency-free SC4 DBPF file containing our UI resources."""

from pathlib import Path
import re
import struct
import sys
import time


UI_SCRIPT_TYPE_ID = 0x00000000
UI_IMAGE_TYPE_ID = 0x856DDBAC
PLUGIN_GROUP_ID = 0x3D0C0700
CONTROL_LAB_INSTANCE_ID = 0x3D0C0701
BASIC_INSTANCE_ID = 0x3D0C0703
GREETING_INSTANCE_ID = 0x3D0C0705
CONTROLS_INSTANCE_ID = 0x3D0C0707
MENU_ICON_INSTANCE_ID = 0x3D0C0900
CHOICE_BUTTON_IMAGE_INSTANCE_ID = 0x3D0C0907
MENU_BUTTON_INSTANCE_ID = 0x3D0C0901
SETTINGS_INSTANCE_ID = 0x3D0C0903
DIAGNOSTICS_INSTANCE_ID = 0x3D0C0905
HEADER_SIZE = 96
CHOICE_BUTTON_IDS = (
    "0x3D0C0930",
    "0x3D0C0931",
    "0x3D0C0932",
    "0x3D0C0933",
    "0x3D0C0936",
    "0x3D0C0937",
    "0x3D0C0940",
    "0x3D0C0941",
    "0x3D0C0942",
    "0x3D0C0943",
    "0x3D0C0968",
    "0x3D0C0969",
    "0x3D0C096A",
)


def rgb_to_565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb_from_565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def encode_dxt3_color_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    opaque_pixels = [(r, g, b) for r, g, b, a in pixels if a > 8]
    if not opaque_pixels:
        opaque_pixels = [(0, 0, 0)]

    min_color = min(opaque_pixels, key=lambda color: color[0] + color[1] * 2 + color[2])
    max_color = max(opaque_pixels, key=lambda color: color[0] + color[1] * 2 + color[2])
    color0 = rgb_to_565(*max_color)
    color1 = rgb_to_565(*min_color)

    # DXT1-compatible color data inside DXT3 uses the four-color mode when
    # color0 is greater than color1. Swap if quantization collapsed/reversed it.
    if color0 <= color1:
        color0, color1 = color1, color0

    c0 = rgb_from_565(color0)
    c1 = rgb_from_565(color1)
    palette = [
        c0,
        c1,
        tuple((2 * c0[i] + c1[i]) // 3 for i in range(3)),
        tuple((c0[i] + 2 * c1[i]) // 3 for i in range(3)),
    ]

    indices = 0
    for i, (r, g, b, _a) in enumerate(pixels):
        best_index = min(
            range(4),
            key=lambda index: (
                (palette[index][0] - r) ** 2
                + (palette[index][1] - g) ** 2
                + (palette[index][2] - b) ** 2
            ),
        )
        indices |= best_index << (2 * i)

    return struct.pack("<HHI", color0, color1, indices)


def encode_dxt3_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    alpha_bits = 0
    for i, (_r, _g, _b, a) in enumerate(pixels):
        alpha_bits |= max(0, min(15, round(a / 17))) << (4 * i)
    return alpha_bits.to_bytes(8, "little") + encode_dxt3_color_block(pixels)


def encode_dxt3_rgba(image) -> bytes:
    width, height = image.size
    if width % 4 != 0 or height % 4 != 0:
        raise RuntimeError(f"DXT3 images must be multiples of 4 pixels, got {width}x{height}")

    pixels = image.load()
    output = bytearray()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            block = []
            for row in range(4):
                for col in range(4):
                    block.append(pixels[x + col, y + row])
            output.extend(encode_dxt3_block(block))
    return bytes(output)


def build_fsh_dxt3_from_png(png_path: Path, image_id: bytes = b"3DMCICON") -> bytes:
    if len(image_id) != 8:
        raise RuntimeError("FSH image IDs must be exactly 8 bytes")

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to package PNG UI images") from exc

    image = Image.open(png_path).convert("RGBA")
    width, height = image.size
    payload = encode_dxt3_rgba(image)

    # Minimal one-image SHPI/FSH payload. Format 0x61 was verified against a
    # Reader-exported decoded FSH sample as DXT3.
    image_offset = 0x20
    total_size = image_offset + 16 + len(payload)
    header = bytearray()
    header.extend(b"SHPI")
    header.extend(struct.pack("<I", total_size))
    header.extend(struct.pack("<I", 1))
    header.extend(b"G264")
    header.extend(b"NONE")
    header.extend(struct.pack("<I", image_offset))
    header.extend(image_id)
    header.extend(struct.pack("<B3sHHHHI", 0x61, b"\0\0\0", width, height, 0, 0, 0))
    header.extend(payload)

    if len(header) != total_size:
        raise RuntimeError(f"Internal FSH size mismatch: expected {total_size}, got {len(header)}")
    return bytes(header)


def escape_ui_caption(text: str) -> str:
    return (
        text.replace('"', "'")
        .replace("<", "[")
        .replace(">", "]")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def apply_choice_button_image(script: str) -> str:
    for control_id in CHOICE_BUTTON_IDS:
        script = re.sub(
            rf"(<LEGACY clsid=GZWinBtn[^\n]*id={control_id}[^\n]*?)image=\{{46a006b0,144161eb\}}",
            rf"\1image={{{PLUGIN_GROUP_ID:08x},{CHOICE_BUTTON_IMAGE_INSTANCE_ID:08x}}}",
            script,
        )
    return script


def read_plugin_version(version_header: Path) -> str:
    text = version_header.read_text(encoding="utf-8")
    match = re.search(r'inline\s+constexpr\s+char\s+String\[\]\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError(f"Could not read PluginVersion::String from {version_header}")
    return match.group(1)


def build_greeting_script(changelog_path: Path, version_header: Path) -> bytes:
    version = read_plugin_version(version_header)
    changelog_body = changelog_path.read_text(encoding="utf-8").strip()
    changelog = escape_ui_caption(
        f"SC4-3DMouseCam v{version} installed!\n\n"
        "Camera Options are available from the camera settings button in the upper right of the screen.\n\n"
        f"{changelog_body}"
    )
    script = f"""# Generated for SC4-3DMouseCam's first-install greeting window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0706 area=(0,0,520,320) fillcolor=(228,231,238) caption="SC4-3DMouseCam Greeting" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,6bb93cb5}} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0840 area=(490,10,512,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161f9}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{00000000,ca5c3239}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0841 area=(20,4,478,30) fillcolor=(0,0,0) caption="SC4-3DMouseCam" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0842 area=(24,62,496,246) fillcolor=(0,0,0) caption="{changelog}" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0844 area=(24,274,184,302) fillcolor=(204,204,204) caption="View Controls" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0843 area=(340,274,500,302) fillcolor=(204,204,204) caption="OK" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
</CHILDREN>
</LEGACY>
"""
    return apply_choice_button_image(script).encode("utf-8")


def build_controls_script() -> bytes:
    controls = escape_ui_caption(
        "Controls:\n"
        "WASD: Move Camera (optional)\n"
        "Scroll Wheel: Zoom\n"
        "Mouse 3 + Drag: Pan & Tilt"
    )
    script = f"""# Generated for SC4-3DMouseCam's controls help window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0708 area=(0,0,360,210) fillcolor=(228,231,238) caption="SC4-3DMouseCam Controls" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,6bb93cb5}} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0850 area=(330,10,352,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161f9}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{00000000,ca5c3239}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0851 area=(20,4,318,30) fillcolor=(0,0,0) caption="Controls" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0852 area=(24,62,336,142) fillcolor=(0,0,0) caption="{controls}" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0853 area=(180,164,340,192) fillcolor=(204,204,204) caption="OK" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
</CHILDREN>
</LEGACY>
"""
    return apply_choice_button_image(script).encode("utf-8")


def build_menu_button_script() -> bytes:
    script = """# Generated for SC4-3DMouseCam's floating settings menu button
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0902 area=(0,0,44,44) fillcolor=(0,0,0) caption="SC4-3DMouseCam Menu Button" winflag_visible=yes winflag_enabled=yes winflag_moveable=no winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=no winflag_mousetrans=no winflag_ignoremouse=no userdata=0 moveable=no sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no titlebar=no fill=no outline=no paint=no sidebar=no gutters=(0,0) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0910 area=(0,0,44,44) fillcolor=(0,0,0) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=no winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={3d0c0700,3d0c0900} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="SC4-3DMouseCam Settings" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
</CHILDREN>
</LEGACY>
"""
    return script.encode("utf-8")


def build_settings_script_legacy() -> bytes:
    script = """# Generated for SC4-3DMouseCam's camera settings window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0904 area=(0,0,520,480) fillcolor=(228,231,238) caption="SC4-3DMouseCam Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,6bb93cb5} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0920 area=(490,10,512,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161f9} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={00000000,ca5c3239} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0921 area=(20,4,478,30) fillcolor=(0,0,0) caption="SC4-3DMouseCam Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0922 area=(24,48,496,70) fillcolor=(0,0,0) caption="Camera" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0923 area=(36,82,210,104) fillcolor=(0,0,0) caption="Camera mode:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0930 area=(220,78,340,106) fillcolor=(204,204,204) caption="Modern" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0931 area=(352,78,472,106) fillcolor=(204,204,204) caption="Classic" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0924 area=(36,122,220,144) fillcolor=(0,0,0) caption="WASD Movement:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0932 area=(220,118,340,146) fillcolor=(204,204,204) caption="On" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0933 area=(352,118,472,146) fillcolor=(204,204,204) caption="Off" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0925 area=(36,162,220,184) fillcolor=(0,0,0) caption="Rotation sensitivity:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinSlider iid=IGZWinSlider id=0x3D0C0934 area=(220,160,472,182) fillcolor=(0,0,0) winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no minmaxvalue=(10,300) direction=horizontal image={46a006b0,46a006a7} initvalue=100 >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0926 area=(36,202,220,224) fillcolor=(0,0,0) caption="Zoom sensitivity:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinSlider iid=IGZWinSlider id=0x3D0C0935 area=(220,200,472,222) fillcolor=(0,0,0) winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no minmaxvalue=(10,300) direction=horizontal image={46a006b0,46a006a7} initvalue=100 >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0927 area=(36,242,220,264) fillcolor=(0,0,0) caption="Invert vertical rotation:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0937 area=(220,238,340,266) fillcolor=(204,204,204) caption="Off" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0936 area=(352,238,472,266) fillcolor=(204,204,204) caption="On" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0938 area=(220,278,472,306) fillcolor=(204,204,204) caption="Reset Camera Location" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0928 area=(24,324,496,346) fillcolor=(0,0,0) caption="Redraw Aggression" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0940 area=(36,356,136,384) fillcolor=(204,204,204) caption="Classic" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0941 area=(148,356,248,384) fillcolor=(204,204,204) caption="Normal" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0942 area=(260,356,360,384) fillcolor=(204,204,204) caption="High" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0943 area=(372,356,492,384) fillcolor=(204,204,204) caption="Extreme" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=yes shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="Extreme redraw heavily stresses the engine." tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0929 area=(36,396,492,420) fillcolor=(0,0,0) caption="Only affects Modern camera" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(96,64,32) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0950 area=(24,438,144,466) fillcolor=(204,204,204) caption="Defaults" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Restore default settings" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0951 area=(150,438,270,466) fillcolor=(204,204,204) caption="Diagnostics" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0952 area=(276,438,396,466) fillcolor=(204,204,204) caption="Changelog" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Read changelog" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0953 area=(402,438,492,466) fillcolor=(204,204,204) caption="Close" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
</CHILDREN>
</LEGACY>
"""
    return script.encode("utf-8")


def build_diagnostics_script_legacy() -> bytes:
    body = escape_ui_caption(
        "Diagnostics\n\n"
        "Debug Logging:\n"
        "Off > Normal > Verbose\n\n"
        "Log Location:\n"
        "Plugins/SC4-3DMouseCam/SC4-3DMouseCam.log\n\n"
        "A full diagnostics submenu will be wired here next."
    )
    script = f"""# Generated for SC4-3DMouseCam's diagnostics window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0906 area=(0,0,460,300) fillcolor=(228,231,238) caption="SC4-3DMouseCam Diagnostics" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,6bb93cb5}} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0960 area=(430,10,452,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161f9}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{00000000,ca5c3239}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0961 area=(20,4,418,30) fillcolor=(0,0,0) caption="Diagnostics" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0962 area=(24,62,436,220) fillcolor=(0,0,0) caption="{body}" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0963 area=(276,254,436,282) fillcolor=(204,204,204) caption="Close" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
</CHILDREN>
</LEGACY>
"""
    return script.encode("utf-8")


def build_settings_script() -> bytes:
    script = """# Generated for SC4-3DMouseCam's camera settings window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0904 area=(0,0,520,480) fillcolor=(228,231,238) caption="SC4-3DMouseCam Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,6bb93cb5} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0920 area=(490,10,512,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161f9} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={00000000,ca5c3239} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0921 area=(20,4,478,30) fillcolor=(0,0,0) caption="SC4-3DMouseCam Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0922 area=(24,48,496,70) fillcolor=(0,0,0) caption="Camera" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0923 area=(36,82,210,104) fillcolor=(0,0,0) caption="Camera mode:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0930 area=(220,78,340,106) fillcolor=(204,204,204) caption="Modern" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0931 area=(352,78,472,106) fillcolor=(204,204,204) caption="Classic" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C092A area=(24,120,496,122) fillcolor=(150,160,180) caption="" winflag_visible=yes winflag_enabled=no winflag_moveable=no winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes userdata=0 moveable=no sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(0,0) winflag_enable=no alphablend=no >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C092B area=(24,136,496,158) fillcolor=(0,0,0) caption="Modern" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0924 area=(36,174,220,196) fillcolor=(0,0,0) caption="WASD Movement:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0932 area=(220,170,340,198) fillcolor=(204,204,204) caption="On" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0933 area=(352,170,472,198) fillcolor=(204,204,204) caption="Off" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0925 area=(36,214,220,236) fillcolor=(0,0,0) caption="Rotation sensitivity:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinSlider iid=IGZWinSlider id=0x3D0C0934 area=(220,212,472,234) fillcolor=(0,0,0) winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no minmaxvalue=(10,300) direction=horizontal image={46a006b0,46a006a7} initvalue=100 >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0926 area=(36,254,220,276) fillcolor=(0,0,0) caption="Zoom sensitivity:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinSlider iid=IGZWinSlider id=0x3D0C0935 area=(220,252,472,274) fillcolor=(0,0,0) winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no minmaxvalue=(10,300) direction=horizontal image={46a006b0,46a006a7} initvalue=100 >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0927 area=(36,294,220,316) fillcolor=(0,0,0) caption="Invert vertical rotation:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0937 area=(220,290,340,318) fillcolor=(204,204,204) caption="Off" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0936 area=(352,290,472,318) fillcolor=(204,204,204) caption="On" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0938 area=(220,330,472,358) fillcolor=(204,204,204) caption="Reset Camera Location" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0951 area=(220,370,472,398) fillcolor=(204,204,204) caption="Advanced Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C092C area=(24,420,496,422) fillcolor=(150,160,180) caption="" winflag_visible=yes winflag_enabled=no winflag_moveable=no winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes userdata=0 moveable=no sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(0,0) winflag_enable=no alphablend=no >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0950 area=(24,438,144,466) fillcolor=(204,204,204) caption="Defaults" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Restore default settings" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0952 area=(246,438,386,466) fillcolor=(204,204,204) caption="Show Changelog" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=yes shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Read changelog" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0953 area=(402,438,492,466) fillcolor=(204,204,204) caption="Close" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,144161eb} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=yes shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={ca47efd9,4a5c31d7} >
</CHILDREN>
</LEGACY>
"""
    return apply_choice_button_image(script).encode("utf-8")


def build_diagnostics_script() -> bytes:
    diagnostics_note = escape_ui_caption(
        "Normal logs settings and camera state changes. Verbose adds input and redraw timer traces.\n"
        "Log: Plugins/SC4-3DMouseCam/SC4-3DMouseCam.log"
    )
    script = f"""# Generated for SC4-3DMouseCam's advanced settings window
<LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0906 area=(0,0,520,400) fillcolor=(228,231,238) caption="SC4-3DMouseCam Advanced Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,6bb93cb5}} blttype=edge userdata=0 moveable=yes sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no closedisabled=no gobackdisabled=no minmaxdisabled=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(4,4) winflag_enable=no alphablend=no >
<CHILDREN>
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0960 area=(490,10,512,30) fillcolor=(204,204,204) caption="" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161f9}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no tips=yes tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="Close" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{00000000,ca5c3239}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0961 area=(20,4,478,30) fillcolor=(0,0,0) caption="Advanced Settings" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0962 area=(24,48,496,70) fillcolor=(0,0,0) caption="Redraw Aggression" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0940 area=(24,86,124,114) fillcolor=(204,204,204) caption="Classic" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0941 area=(136,86,236,114) fillcolor=(204,204,204) caption="Normal" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0942 area=(248,86,348,114) fillcolor=(204,204,204) caption="High" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0943 area=(360,86,496,114) fillcolor=(204,204,204) caption="Extreme" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=yes shiftcaption=yes tips=yes tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="Extreme redraw heavily stresses the engine." tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0964 area=(24,126,496,154) fillcolor=(0,0,0) caption="Only affects Modern camera" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(96,64,32) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinGen iid=IGZWinGen id=0x3D0C0965 area=(24,172,496,174) fillcolor=(150,160,180) caption="" winflag_visible=yes winflag_enabled=no winflag_moveable=no winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes userdata=0 moveable=no sizeable=no defaultkeys=no closevisible=no gobackvisible=no minmaxvisible=no titlebar=no fill=yes outline=no paint=yes sidebar=no gutters=(0,0) winflag_enable=no alphablend=no >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0966 area=(24,192,496,214) fillcolor=(0,0,0) caption="Diagnostics" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenHeader align=lefttop notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0967 area=(36,224,160,246) fillcolor=(0,0,0) caption="Debug Logging:" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=leftcenter notify=no wrapped=no opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0968 area=(172,220,252,248) fillcolor=(204,204,204) caption="Off" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0969 area=(264,220,364,248) fillcolor=(204,204,204) caption="Normal" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C096A area=(376,220,496,248) fillcolor=(204,204,204) caption="Verbose" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=on triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=yes shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=toggle gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C096B area=(24,268,496,330) fillcolor=(0,0,0) caption="{diagnostics_note}" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium align=lefttop notify=no wrapped=yes opaque=no forecolor=(32,40,80) bkgcolor=(0,0,0) gutters=(2,2) >
   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0963 area=(402,356,492,384) fillcolor=(204,204,204) caption="Close" winflag_visible=yes winflag_enabled=yes winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=yes winflag_pbufftrans=no winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=yes winflag_acceptfocus=yes winflag_mousetrans=no winflag_ignoremouse=no image={{46a006b0,144161eb}} font=GenButton colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) toggle=off triggerondown=off showcaption=yes fill=yes autosize=no wrapcaption=no shiftcaption=yes tips=no tipsdelay=no tipstimeout=no style=standard gutters=(0,0,0,0) tiptext="" tipoffsets=(0,0) tipflag=0x01000000 align=center btnclicksnd={{ca47efd9,4a5c31d7}} >
</CHILDREN>
</LEGACY>
"""
    return apply_choice_button_image(script).encode("utf-8")


def build(source: Path, destination: Path) -> None:
    script = source.read_text(encoding="utf-8")
    # Ordinance-style checkboxes are a small radio-check bitmap button with a
    # separate label. Using the standard wide-button bitmap with radiocheck
    # makes SC4 read the wrong state atlas and display back-buffer garbage.
    checkbox = (
        '   <LEGACY clsid=GZWinBtn iid=IGZWinBtn id=0x3D0C0734 area=(28,178,48,200) '
        'fillcolor=(204,204,204) winflag_visible=yes winflag_enabled=yes winflag_moveable=yes '
        'winflag_sizeable=no winflag_sortable=no winflag_pbuff=no winflag_pbufftrans=yes '
        'winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no winflag_acceptfocus=yes '
        'winflag_mousetrans=no winflag_ignoremouse=no image={46a006b0,14416245} font=GenBodyMedium '
        'colorfontnormal=(63,73,103) colorfontdisabled=(102,102,102) colorfonthilited=(63,73,103) '
        'colorfontnormalbkg=(0,0,0) colorfontdisabledbkg=(0,0,0) colorfonthilitedbkg=(0,0,0) '
        'toggle=on triggerondown=off showcaption=no fill=yes autosize=no wrapcaption=no shiftcaption=no '
        'tips=no tipsdelay=no tipstimeout=no style=radiocheck gutters=(10,3,10,3) tiptext="" '
        'tipoffsets=(0,0) tipflag=0x01000000 align=right btnclicksnd={ca4d1943,8a5c324a} >\n'
        '   <LEGACY clsid=GZWinText iid=IGZWinText id=0x3D0C0738 area=(54,178,208,200) '
        'fillcolor=(0,0,0) caption="Checkbox Test" winflag_visible=yes winflag_enabled=yes '
        'winflag_moveable=yes winflag_sizeable=no winflag_sortable=no winflag_pbuff=no '
        'winflag_pbufftrans=yes winflag_pbufferase=yes winflag_pbuffvid=no winflag_alphablend=no '
        'winflag_acceptfocus=no winflag_mousetrans=yes winflag_ignoremouse=yes font=GenBodyMedium '
        'align=leftcenter notify=no wrapped=no opaque=no forecolor=(63,73,103) bkgcolor=(0,0,0) '
        'gutters=(2,2) >'
    )
    script = re.sub(
        r"^.*<LEGACY clsid=GZWinBtn[^\r\n]*id=0x3D0C0734[^\r\n]*$",
        checkbox,
        script,
        flags=re.MULTILINE,
    )
    resources = [(UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, CONTROL_LAB_INSTANCE_ID, script.encode("utf-8"))]
    basic_source = source.with_name("SC4-3DMouseCam-BasicUI.txt")
    if basic_source.exists():
        resources.append((UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, BASIC_INSTANCE_ID, basic_source.read_bytes()))
    changelog_source = source.parents[2] / "docs" / "changelog.md"
    version_header = source.parents[1] / "src" / "PluginVersion.h"
    if changelog_source.exists():
        resources.append(
            (UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, GREETING_INSTANCE_ID, build_greeting_script(changelog_source, version_header))
        )
        resources.append((UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, CONTROLS_INSTANCE_ID, build_controls_script()))
        resources.append((UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, MENU_BUTTON_INSTANCE_ID, build_menu_button_script()))
        resources.append((UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, SETTINGS_INSTANCE_ID, build_settings_script()))
        resources.append((UI_SCRIPT_TYPE_ID, PLUGIN_GROUP_ID, DIAGNOSTICS_INSTANCE_ID, build_diagnostics_script()))

    menu_icon_source = source.with_name("3dm-menu-icon.png")
    if menu_icon_source.exists():
        resources.append(
            (
                UI_IMAGE_TYPE_ID,
                PLUGIN_GROUP_ID,
                MENU_ICON_INSTANCE_ID,
                build_fsh_dxt3_from_png(menu_icon_source),
            )
        )

    choice_button_source = source.with_name("menu-button-stages.png")
    if choice_button_source.exists():
        resources.append(
            (
                UI_IMAGE_TYPE_ID,
                PLUGIN_GROUP_ID,
                CHOICE_BUTTON_IMAGE_INSTANCE_ID,
                build_fsh_dxt3_from_png(choice_button_source, b"3DMCBTNS"),
            )
        )

    payload = bytearray()
    index_entries = []
    for type_id, group_id, instance_id, resource_data in resources:
        offset = HEADER_SIZE + len(payload)
        payload.extend(resource_data)
        index_entries.append(
            struct.pack("<IIIII", type_id, group_id, instance_id, offset, len(resource_data))
        )

    index_offset = HEADER_SIZE + len(payload)
    header = bytearray(HEADER_SIZE)
    header[0:4] = b"DBPF"
    struct.pack_into("<II", header, 4, 1, 0)
    now = int(time.time())
    struct.pack_into("<II", header, 0x18, now, now)
    struct.pack_into("<IIII", header, 0x20, 7, len(resources), index_offset, 20 * len(resources))
    struct.pack_into("<III", header, 0x30, 0, 0, 0)
    struct.pack_into("<I", header, 0x3C, 0)
    index = b"".join(index_entries)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + payload + index)
    print(f"Wrote {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_sc4_ui_dat.py SOURCE DESTINATION")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
