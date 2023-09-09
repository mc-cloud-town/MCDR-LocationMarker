import json
import os
import re
from typing import Any, Callable, Optional, Union

from mcdreforged.api.all import (
    CommandSource,
    GreedyText,
    Integer,
    Literal,
    Number,
    PlayerCommandSource,
    PluginServerInterface,
    QuotableText,
    RAction,
    RColor,
    RText,
    RTextBase,
    RTextList,
    Serializable,
    ServerInterface,
    new_thread,
)

from location_marker import constants
from location_marker.storage import Location, LocationStorage, Point


class Config(Serializable):
    teleport_hint_on_coordinate: bool = True
    item_per_page: int = 10
    display_voxel_waypoint: bool = True
    display_xaero_waypoint: bool = True


config: Config = None
storage = LocationStorage()
server_inst: PluginServerInterface


def show_help(source: CommandSource):
    help_msg_lines = """
--------- MCDR 路標插件 v{2} ---------
一個位於服務端的路標管理插件
§7{0}§r 顯示此幫助信息
§7{0} list §6[<可選頁號>]§r 列出所有路標
§7{0} search §3<關鍵字> §6[<可選頁號>]§r 搜索坐標，返回所有匹配項
§7{0} add §b<路標名稱> §e<x> <y> <z> <維度id> §6[<可選注釋>]§r 加入一個路標
§7{0} add §b<路標名稱> §ehere §6[<可選注釋>]§r 加入自己所處位置、維度的路標
§7{0} del §b<路標名稱>§r 刪除路標，要求全字匹配
§7{0} info §b<路標名稱>§r 顯示路標的詳情等信息
§7{0} §3<關鍵字> §6[<可選頁號>]§r 同 §7{0} search§r
其中：
當§6可選頁號§r被指定時，將以每{1}個路標為一頁，列出指定頁號的路標
§3關鍵字§r以及§b路標名稱§r為不包含空格的一個字符串，或者一個被""括起的字符串
""".format(
        constants.PREFIX,
        config.item_per_page,
        server_inst.get_self_metadata().version,
    ).splitlines(
        True
    )
    help_msg_rtext = RTextList()
    for line in help_msg_lines:
        result = re.search(r"(?<=§7)!!loc[\w ]*(?=§)", line)
        if result is not None:
            help_msg_rtext.append(
                RText(line)
                .c(RAction.suggest_command, result.group())
                .h(f"點擊以填入 §7{result.group()}§r")
            )
        else:
            help_msg_rtext.append(line)
    source.reply(help_msg_rtext)


def get_coordinate_text(
    coord: Point,
    dimension: int,
    *,
    color=RColor.green,
):
    x, y, z = coord
    x_i, y_i, z_i = map(int, coord)

    return RText(f"[{x_i}, {y_i}, {z_i}]]", color=color).c(
        RAction.suggest_command,
        f"/execute in {get_dim_key(dimension)} run tp {x} {y} {z}",
    )


def get_dim_key(dim: Union[int, str]) -> str:
    dimension_convert = {
        0: "minecraft:overworld",
        -1: "minecraft:the_nether",
        1: "minecraft:the_end",
    }
    return dimension_convert.get(dim, dim)


def get_dimension_text(dim: Union[int, str]) -> RTextBase:
    dim_key = get_dim_key(dim)
    dimension_color = {
        "minecraft:overworld": RColor.dark_green,
        "minecraft:the_nether": RColor.dark_red,
        "minecraft:the_end": RColor.dark_purple,
    }

    # supper versions remove local translations
    dimension_text = {
        "minecraft:overworld": "overworld",
        "minecraft:the_nether": "the_nether",
        "minecraft:the_end": "the_end",
    }

    return RText(
        dimension_text.get(dim_key, dim_key),
        color=dimension_color.get(dim_key, RColor.gray),
    ).h(dim_key)


def print_location(
    location: Location,
    printer: Callable[[RTextBase], Any],
    *,
    show_list_symbol: bool,
):
    name_text = RText(location.name)
    if location.desc is not None:
        name_text.h(location.desc)
    text = RTextList(
        name_text.h("點擊以顯示詳情").c(
            RAction.run_command,
            f"{constants.PREFIX} info {location.name}",
        ),
        " ",
        get_coordinate_text(location.pos, location.dim),
        RText(" @ ", RColor.gray),
        get_dimension_text(location.dim),
    )

    x, y, z = map(int, location.pos)
    if config.display_voxel_waypoint:
        text.append(
            " ",
            RText("[+V]", RColor.aqua)
            .h("§bVoxelmap§r: 點此以高亮坐標點, 或者Ctrl點擊添加路徑點")
            .c(
                RAction.run_command,
                f"/newWaypoint x:{x}, y:{y}, z:{z}, dim:{location.dim}",
            ),
        )
    if config.display_xaero_waypoint:
        name = location.name
        command = (
            f"xaero_waypoint_add:{name}'s Location:{name[0]}:{x}:{y}:{z}:6:false:0"
            f":Internal_{get_dim_key(location.dim).replace('minecraft:', '')}_waypoints"
        )

        text.append(
            " ",
            RText("[+X]", RColor.gold)
            .h("§6Xaeros Minimap§r: 點擊添加路徑點")
            .c(RAction.run_command, command),
        )

    # RText(" -> ", RColor.gray)

    if show_list_symbol:
        text = RText("- ", color=RColor.gray) + text
    printer(text)


def reply_location_as_item(source: CommandSource, location: Location):
    print_location(location, lambda msg: source.reply(msg), show_list_symbol=True)


def broadcast_location(server: ServerInterface, location: Location):
    print_location(location, lambda msg: server.say(msg), show_list_symbol=False)


def list_locations(
    source: CommandSource, *, keyword: Optional[str] = None, page: Optional[int] = None
):
    matched_locations = []
    for loc in storage.get_locations():
        if (
            keyword is None
            or loc.name.find(keyword) != -1
            or (loc.desc is not None and loc.desc.find(keyword) != -1)
        ):
            matched_locations.append(loc)
    matched_count = len(matched_locations)
    if page is None:
        for loc in matched_locations:
            reply_location_as_item(source, loc)
    else:
        command_base = constants.PREFIX
        if keyword is None:
            command_base += " list"
        else:
            command_base += f" search {json.dumps(keyword, ensure_ascii=False)}"
        left, right = (page - 1) * config.item_per_page, page * config.item_per_page
        for i in range(left, right):
            if 0 <= i < matched_count:
                reply_location_as_item(source, matched_locations[i])

        has_prev = 0 < left < matched_count
        has_next = 0 < right < matched_count
        color = {False: RColor.dark_gray, True: RColor.gray}
        prev_page = RText("<-", color=color[has_prev])
        if has_prev:
            prev_page.c(
                RAction.run_command,
                f"{command_base} {page - 1}",
            ).h("點擊顯示上一頁")
        next_page = RText("->", color=color[has_next])
        if has_next:
            next_page.c(RAction.run_command, f"{command_base} {page+1}").h("點擊顯示下一頁")

        source.reply(RTextList(prev_page, f" 第§6{page}§r頁 ", next_page))
    if keyword is None:
        source.reply(f"共有§6{matched_count}§r個路標")
    else:
        source.reply(f"共找到§6{matched_count}§r個路標")


def add_location(source: CommandSource, name, x, y, z, dim, desc=None):
    if storage.contains(name):
        source.reply(f"路標§b{name}§r已存在，無法添加")
        return
    try:
        location = Location(name=name, desc=desc, dim=dim, pos=Point(x=x, y=y, z=z))
        storage.add(location)
    except Exception as e:
        source.reply(f"路標§b{name}§r添加§c失敗§r: {e}")
        server_inst.logger.exception(f"Failed to add location {name}")
    else:
        source.get_server().say(f"路標§b{name}§r添加§a成功")
        broadcast_location(source.get_server(), location)


@new_thread("LocationMarker")
def add_location_here(source: CommandSource, name, desc=None):
    if not isinstance(source, PlayerCommandSource):
        source.reply("僅有玩家允許使用本指令")
        return
    api = source.get_server().get_plugin_instance("minecraft_data_api")
    pos = api.get_player_coordinate(source.player)
    dim = api.get_player_dimension(source.player)
    add_location(source, name, pos.x, pos.y, pos.z, dim, desc)


def delete_location(source: CommandSource, name):
    loc = storage.remove(name)
    if loc is not None:
        source.get_server().say(f"已刪除路標§b{name}§r")
        broadcast_location(source.get_server(), loc)
    else:
        source.reply(f"未找到路標§b{name}§r")


def show_location_detail(source: CommandSource, name):
    loc = storage.get(name)
    if loc is not None:
        broadcast_location(source.get_server(), loc)
        source.reply(RTextList("路標名: ", RText(loc.name, color=RColor.aqua)))
        source.reply(RTextList("坐標: ", get_coordinate_text(loc.pos, loc.dim)))
        source.reply(
            RTextList(
                "詳情: ",
                RText(loc.desc if loc.desc is not None else "無", color=RColor.gray),
            )
        )
    else:
        source.reply(f"未找到路標§b{name}§r")


def on_load(server: PluginServerInterface, old_inst):
    global config, storage, server_inst
    server_inst = server
    config = server.load_config_simple(constants.CONFIG_FILE, target_class=Config)
    storage.load(os.path.join(server.get_data_folder(), constants.STORAGE_FILE))

    server.register_help_message(constants.PREFIX, "路標管理")
    search_node = (
        QuotableText("keyword")
        .runs(lambda src, ctx: list_locations(src, keyword=ctx["keyword"]))
        .then(
            Integer("page").runs(
                lambda src, ctx: list_locations(
                    src, keyword=ctx["keyword"], page=ctx["page"]
                )
            )
        )
    )

    server.register_command(
        Literal(constants.PREFIX)
        .runs(show_help)
        .then(Literal("all").runs(lambda src: list_locations(src)))
        .then(
            Literal("list")
            .runs(lambda src: list_locations(src))
            .then(
                Integer("page").runs(
                    lambda src, ctx: list_locations(src, page=ctx["page"])
                )
            )
        )
        .then(Literal("search").then(search_node))
        .then(search_node)
        .then(  # for lazyman
            Literal("add").then(
                QuotableText("name")
                .then(
                    Literal("here")
                    .runs(lambda src, ctx: add_location_here(src, ctx["name"]))
                    .then(
                        GreedyText("desc").runs(
                            lambda src, ctx: add_location_here(
                                src, ctx["name"], ctx["desc"]
                            )
                        )
                    )
                )
                .then(
                    Number("x").then(
                        Number("y").then(
                            Number("z").then(
                                Integer("dim")
                                .in_range(-1, 1)
                                .runs(
                                    lambda src, ctx: add_location(
                                        src,
                                        ctx["name"],
                                        ctx["x"],
                                        ctx["y"],
                                        ctx["z"],
                                        ctx["dim"],
                                    )
                                )
                                .then(
                                    GreedyText("desc").runs(
                                        lambda src, ctx: add_location(
                                            src,
                                            ctx["name"],
                                            ctx["x"],
                                            ctx["y"],
                                            ctx["z"],
                                            ctx["dim"],
                                            ctx["desc"],
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
        .then(
            Literal("del").then(
                QuotableText("name").runs(
                    lambda src, ctx: delete_location(src, ctx["name"])
                )
            )
        )
        .then(
            Literal("info").then(
                QuotableText("name").runs(
                    lambda src, ctx: show_location_detail(src, ctx["name"])
                )
            )
        )
    )
