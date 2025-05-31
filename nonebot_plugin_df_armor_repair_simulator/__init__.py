import json
import math
from pathlib import Path
from nonebot import on_message, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.params import EventMessage
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher

require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as store

__plugin_meta__ = PluginMetadata(
    name="nonebot_plugin_df_armor_repair_simulator",
    description="《三角洲行动》护甲维修模拟器",
    usage="护甲维修模拟器",
    type="application",
    homepage="https://github.com/2580m/nonebot-plugin-df-armor-repair-simulator",
    supported_adapters={"~onebot.v11"},
)

ARMOR_JSON = store.get_plugin_data_file("armors.json")
HELMET_JSON = store.get_plugin_data_file("helmets.json")

def load_armors():
    with open(ARMOR_JSON, "r", encoding="utf-8") as f:
        return json.load(f)
def load_helmets():
    with open(HELMET_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def save_armors(data):
    with open(ARMOR_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def save_helmets(data):
    with open(HELMET_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 状态缓存
user_armor_state = {}

armor_sim_cmd = on_message(priority=20, block=True)

@armor_sim_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, msg: Message = EventMessage()):
    text = str(msg).strip()
    uid = event.user_id
    gid = event.group_id
    key = f"{gid}_{uid}"

    # 入口指令
    if (text == "护甲维修模拟器"):
        user_armor_state[key] = {"step": "choose_type"}
        await matcher.send(
            "欢迎使用Delta Force Armor Repair Simulator，护甲/头盔数据及公式来自BiliBili@繁星攻略组-熊熊(UID:3546853731731919)。\n"
            "干员，你今天要维修“护甲”还是“头盔捏（请输入“头盔”，“护甲”或“退出”，输入“退出”时会结束护甲维修模拟）"
        )
        return

    # 继续流程
    state = user_armor_state.get(key)
    if not state:
        return

    # 支持任意步骤退出
    if text == "退出":
        user_armor_state.pop(key, None)
        await matcher.send("已退出护甲维修模拟器。")
        return

    # 选择类型
    if state["step"] == "choose_type":
        if text not in ("护甲", "头盔"):
            await matcher.send("请输入“护甲”或“头盔”。")
            return
        state["type"] = text
        state["step"] = "choose_level"
        user_armor_state[key] = state
        await matcher.send(f"请输入你要模拟维修的{state['type']}的等级（3, 4, 5或6）")
        return

    # 选择等级
    if state["step"] == "choose_level":
        if text not in ("3", "4", "5", "6"):
            await matcher.send("请输入3、4、5或6作为等级。")
            return
        state["level"] = text
        state["step"] = "choose_item"
        state["page"] = 1
        user_armor_state[key] = state
        await send_item_list(matcher, state)
        return

    # 翻页
    if state["step"] == "choose_item" and text.startswith("第") and text.endswith("页"):
        try:
            page = int(text[1:-1])
            state["page"] = page
            user_armor_state[key] = state
            await send_item_list(matcher, state)
        except Exception:
            await matcher.send("页码格式错误，请输入如“第2页”。")
        return

    # 选择护甲/头盔
    if state["step"] == "choose_item":
        try:
            idx = int(text)
        except Exception:
            await matcher.send("请输入装备名称前的序号选择，或输入“第x页”翻页。")
            return
        items = get_item_list(state["type"], state["level"])
        page = state.get("page", 1)
        start = (page-1)*10
        if not (1 <= idx <= min(10, len(items)-start)):
            await matcher.send("序号超出范围，请重新输入。")
            return
        item_idx = str(start + idx)
        item = items[item_idx]
        state["item"] = item
        state["step"] = "input_max"
        user_armor_state[key] = state
        await matcher.send(f"你选择了：{item['name']}，请输入当前耐久上限（输入“退出”可结束）")
        return

    # 输入当前上限
    if state["step"] == "input_max":
        try:
            cur_max = float(text)
            if cur_max <= 0:
                raise ValueError
        except Exception:
            await matcher.send("请输入有效的当前耐久上限。")
            return
        state["cur_max"] = cur_max
        state["step"] = "input_cur"
        user_armor_state[key] = state
        await matcher.send("请输入剩余耐久（输入“退出”可结束）")
        return

    # 输入剩余耐久并计算
    if state["step"] == "input_cur":
        try:
            cur = float(text)
            if cur < 0 or cur > state["cur_max"]:
                raise ValueError
        except Exception:
            await matcher.send("请输入有效的剩余耐久。")
            return
        item = state["item"]
        cur_max = state["cur_max"]
        base_max = item["base_max"]
        repair_loss = item["repair_loss"]
        # 维修后上限=当前上限-当前上限*【(当前上限-剩余耐久)/当前上限】*【维修损耗-log10(当前上限/初始上限)】
        try:
            log_part = math.log10(cur_max/base_max) if cur_max > 0 and base_max > 0 else 0
            after = cur_max - cur_max * ((cur_max-cur)/cur_max) * (repair_loss - log_part)
            after = round(after, 1)
        except Exception:
            await matcher.send("计算出错，请检查输入。")
            user_armor_state.pop(key, None)
            return
        # 判断能否上架交易行
        min_market = item.get("min_market")
        if min_market is not None:
            if after >= min_market:
                compare_msg = "该装备可以上架交易行"
            else:
                compare_msg = "该装备已不能上架交易行"
        else:
            compare_msg = "（未配置上架交易行最低耐久上限）"
        # 计算维修金额
        repair_price = item.get("repair_price", None)
        if repair_price is not None:
            try:
                repair_cost = (after - cur + 1) * repair_price
                repair_cost = int(repair_cost)  # 去尾取整
                price_msg = f"局外中级维修金额为：{repair_cost}"
            except Exception:
                price_msg = "局外维修金额计算出错"
        else:
            price_msg = "（未配置维修单价，无法计算维修金额）"
        await matcher.send(f"维修后上限为：{after}\n{compare_msg}\n{price_msg}")
        user_armor_state.pop(key, None)
        return

def get_item_list(item_type: str, level: str):
    if item_type == "护甲":
        data = load_armors()
    else:
        data = load_helmets()
    items = []
    for idx, (k, v) in enumerate(sorted(data.get(level, {}).items(), key=lambda x: int(x[0])), 1):
        items.append((str(idx), v))
    return dict(items)

async def send_item_list(matcher: Matcher, state: dict):
    item_type = state["type"]
    level = state["level"]
    items = get_item_list(item_type, level)
    page = state.get("page", 1)
    per_page = 10
    total = len(items)
    pages = (total+per_page-1)//per_page
    start = (page-1)*per_page
    end = start+per_page
    items_on_page = list(items.items())[start:end]
    if not items_on_page:
        await matcher.send(f"该等级暂无{item_type}。")
        return
    msg = f"【{level}级{item_type}列表 第{page}/{pages}页】\n"
    for idx, item in items_on_page:
        msg += f"{int(idx)-start}. {item['name']}（维修损耗:{item['repair_loss']} 初始上限:{item['base_max']}）\n"
    if pages > 1:
        msg += "输入“第x页”翻页。\n"
    msg += "请输入装备名称前的序号选择。"
    await matcher.send(msg)