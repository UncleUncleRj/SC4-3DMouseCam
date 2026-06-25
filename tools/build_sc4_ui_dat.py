"""Build the dependency-free SC4 DBPF file containing our UI script."""

from pathlib import Path
import re
import struct
import sys
import time


TYPE_ID = 0x00000000
GROUP_ID = 0x3D0C0700
INSTANCE_ID = 0x3D0C0701
BASIC_INSTANCE_ID = 0x3D0C0703
GREETING_INSTANCE_ID = 0x3D0C0705
CONTROLS_INSTANCE_ID = 0x3D0C0707
HEADER_SIZE = 96


def escape_ui_caption(text: str) -> str:
    return (
        text.replace('"', "'")
        .replace("<", "[")
        .replace(">", "]")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def read_plugin_version(version_header: Path) -> str:
    text = version_header.read_text(encoding="utf-8")
    match = re.search(r'inline\s+constexpr\s+char\s+String\[\]\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError(f"Could not read PluginVersion::String from {version_header}")
    return match.group(1)


def build_greeting_script(changelog_path: Path, version_header: Path) -> bytes:
    version = read_plugin_version(version_header)
    changelog_body = changelog_path.read_text(encoding="utf-8").strip()
    changelog = escape_ui_caption(f"SC4-3DMouseCam v{version} installed!\n\n{changelog_body}")
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
    return script.encode("utf-8")


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
    return script.encode("utf-8")


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
    resources = [(INSTANCE_ID, script.encode("utf-8"))]
    basic_source = source.with_name("SC4-3DMouseCam-BasicUI.txt")
    if basic_source.exists():
        resources.append((BASIC_INSTANCE_ID, basic_source.read_bytes()))
    changelog_source = source.parents[2] / "docs" / "changelog.md"
    version_header = source.parents[1] / "src" / "PluginVersion.h"
    if changelog_source.exists():
        resources.append((GREETING_INSTANCE_ID, build_greeting_script(changelog_source, version_header)))
        resources.append((CONTROLS_INSTANCE_ID, build_controls_script()))

    payload = bytearray()
    index_entries = []
    for instance_id, resource_data in resources:
        offset = HEADER_SIZE + len(payload)
        payload.extend(resource_data)
        index_entries.append(
            struct.pack("<IIIII", TYPE_ID, GROUP_ID, instance_id, offset, len(resource_data))
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
