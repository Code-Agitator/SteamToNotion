# main.py（带游戏选择功能）
import requests
from notion_client import Client
import os
from dotenv import load_dotenv
from datetime import datetime
import re
import time
from collections import defaultdict

# === 配置参数 ===
load_dotenv()
notion = Client(auth=os.getenv("NOTION_TOKEN"))

STEAM_RETRY_TIMES = 5  # 从3增加到5
STEAM_TIMEOUT = 30  # 从25增加到30
REQUEST_DELAY = 2  # 从1增加到2
MAX_TAGS = 5
MAX_DEVELOPERS = 3

NOTION_RETRY_TIMES = 5  # 从3增加到5
NOTION_DELAY = 3  # 从1.5增加到3


# === 工具函数 ===
def clean_zh_text(text):
    """中文文本清洗"""
    return re.sub(r"""[^\u4e00-\u9fa5a-zA-Z0-9\-—，。？！、："'()（）·]""", '', str(text)) if text else ""


def timestamp_to_iso(timestamp):
    """时间戳转换"""
    try:
        return datetime.utcfromtimestamp(int(timestamp)).isoformat() + "Z" if timestamp else None
    except:
        return None


def parse_any_date(date_str):
    """增强版日期解析（确保始终返回有效字符串）"""
    if not date_str:
        return "1970-01-01"  # 默认日期

    clean_str = re.sub(r'[\u4e00-\u9fa5]+\s*\(.*?\)', '', str(date_str)).strip()

    formats = [
        "%Y年%m月%d日", "%Y.%m.%d", "%Y-%m-%d",
        "%d %b %Y", "%b %d %Y", "%B %d %Y",
        "%Y年%m月", "%Y-%m", "%b %Y", "%B %Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(clean_str, fmt).date().isoformat()
        except ValueError:
            continue

    if year_match := re.search(r'\b(19|20)\d{2}\b', clean_str):
        return f"{year_match.group()}-01-01"

    return "1970-01-01"


def clean_url(url):
    """URL清理"""
    if not url:
        return ""
    return url.split('?')[0].strip()


def display_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """显示进度条"""
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end='\r')
    if iteration == total:
        print()


# === Steam API 交互 ===
def get_steam_games():
    """获取Steam游戏库"""
    url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={os.getenv('STEAM_API_KEY')}&steamid={os.getenv('STEAM_ID')}&include_appinfo=1"

    for attempt in range(1, STEAM_RETRY_TIMES + 1):
        try:
            response = requests.get(url, timeout=STEAM_TIMEOUT)
            if response.status_code == 200:
                games = response.json().get("response", {}).get("games", [])
                # 按游戏时长排序（从高到低）
                return sorted(games, key=lambda x: x.get("playtime_forever", 0), reverse=True)
            print(f"⚠️ Steam API请求失败 (尝试 {attempt}/{STEAM_RETRY_TIMES})")
        except Exception as e:
            print(f"⚠️ Steam API异常 (尝试 {attempt}/{STEAM_RETRY_TIMES}): {str(e)}")
        time.sleep(REQUEST_DELAY * attempt)
    return []


def get_game_details_with_cover(appid):
    """获取包含封面URL的游戏详情（过滤非游戏标签）"""
    EXCLUDE_TAGS = {
        "集换式卡牌", "成就", "云存储", "排行榜", "关卡编辑器",
        "创意工坊", "共享/分屏", "控制器", "远程畅玩", "内购",
        "游戏内广告", "免费开玩", "可以仅用触控", "自定义音量控制", "Steam成就", "同屏分屏",
        "应用内购买", "线上玩家对战", "在手机上远程畅玩", "在平板上远程畅玩", "可调整文字大小",
        "在电视上远程畅玩", "Steam集换式卡牌", "Steam云", "家庭共享", "Steam排行榜", "统计数据",
        "完全支持控制器", "Steam创意工坊", "包含关卡编辑器", "无需应对快速反应事件", "跨平台多人",
        "在线合作", "可选颜色", "环绕声", "立体声", "可用HDR", "抢先体验", "远程同乐", "定位控制器支持",
        "Steam时间轴", "已启用Valve反作弊保护", "视角舒适度", "聊天语音转文字"
    }

    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese"
    store_url = f"https://store.steampowered.com/app/{appid}/"

    for attempt in range(1, STEAM_RETRY_TIMES + 1):
        try:
            response = requests.get(url, timeout=STEAM_TIMEOUT)
            data = response.json().get(str(appid), {}).get("data", {})

            # 过滤标签逻辑（只保留游戏类型相关的标签）
            valid_tags = []
            for item_type in ["genres", "categories"]:
                for item in data.get(item_type, []):
                    tag = clean_zh_text(item.get("description", ""))
                    if tag and tag not in EXCLUDE_TAGS and len(tag) < 20:  # 额外限制标签长度
                        valid_tags.append(tag)

            return {
                "name": clean_zh_text(data.get("name", "")),
                "cover_url": clean_url(data.get("header_image")),
                "store_url": store_url,  # 新增商店链接
                "zh_tags": list(set(valid_tags))[:MAX_TAGS],  # 去重并限制数量
                "developers": data.get("developers", [])[:MAX_DEVELOPERS],
                "release_date": data.get("release_date", {}).get("date"),
                "metacritic": max(0, min(100, data.get("metacritic", {}).get("score", 0)))
            }
        except Exception as e:
            print(f"⚠️ 游戏 {appid} 详情获取失败 (尝试 {attempt}/{STEAM_RETRY_TIMES}): {str(e)}")
            time.sleep(REQUEST_DELAY * attempt)
    return {}


# === 用户交互 ===
def select_games_to_import(all_games):
    """让用户选择要导入的游戏"""
    print("\n=== 发现以下游戏 ===")
    print("序号 | 游戏名 (游玩时长小时) [AppID]")
    print("-" * 60)

    # 按游戏时长分组
    hour_ranges = {
        "100+小时": (100, float('inf')),
        "50-100小时": (50, 100),
        "10-50小时": (10, 50),
        "1-10小时": (1, 10),
        "<1小时": (0, 1)
    }

    games_by_hours = defaultdict(list)

    # 显示游戏列表并分组
    for idx, game in enumerate(all_games, 1):
        hours = round(game.get("playtime_forever", 0) / 60, 1)
        game_name = game.get("name", f"未知游戏 ({game['appid']})")

        # 显示游戏信息
        print(f"{idx:3} | {game_name[:50]:50} ({hours}小时) [{game['appid']}]")

        # 分组游戏
        for range_name, (min_h, max_h) in hour_ranges.items():
            if min_h <= hours < max_h:
                games_by_hours[range_name].append(game)
                break

    print("\n=== 请选择要导入的游戏 ===")
    print("0. 导入所有游戏")

    # 显示按游玩时长分组的选项
    for i, (range_name, games) in enumerate(games_by_hours.items(), 1):
        print(f"{i}. 导入所有{range_name}的游戏 ({len(games)}个)")

    print(f"{len(hour_ranges) + 1}. 手动选择要导入的游戏")

    # while True:
    #     try:
    #         choice = int(input("\n请输入您的选择: "))
    #         if 0 <= choice <= len(hour_ranges) + 1:
    #             break
    #         print("⚠️ 请输入有效的选项编号")
    #     except ValueError:
    #         print("⚠️ 请输入数字")
    choice = 0
    if choice == 0:
        return all_games
    elif 1 <= choice <= len(hour_ranges):
        selected_range = list(hour_ranges.keys())[choice - 1]
        return games_by_hours[selected_range]
    else:
        # 手动选择模式
        print("\n=== 手动选择模式 ===")
        print("请输入要导入的游戏序号，多个序号用空格分隔 (例如: 1 3 5)")
        print("或输入范围 (例如: 1-5)")

        while True:
            selections = input("请输入您的选择: ").strip()

            if selections.lower() == 'all':
                return all_games

            selected_indices = set()
            valid = True

            for part in selections.split():
                if '-' in part:
                    try:
                        start, end = map(int, part.split('-'))
                        if 1 <= start <= end <= len(all_games):
                            selected_indices.update(range(start - 1, end))
                        else:
                            valid = False
                            break
                    except:
                        valid = False
                        break
                else:
                    try:
                        idx = int(part)
                        if 1 <= idx <= len(all_games):
                            selected_indices.add(idx - 1)
                        else:
                            valid = False
                            break
                    except:
                        valid = False
                        break

            if valid and selected_indices:
                return [all_games[i] for i in sorted(selected_indices)]
            print("⚠️ 输入无效，请重新输入")


def create_store_url_map_for_pages(pages_array):
    """
    为页面数组创建appid映射

    Args:
        pages_array: Notion页面数据数组

    Returns:
        dict: {appid: 页面ID}
    """
    appid_map = {}

    for page in pages_array:
        page_id = page.get("id")
        # 从appid字段提取真实的appid（去除$前缀）
        appid_content = page.get("properties", {}).get("appid", {}).get("rich_text", [])
        if appid_content:
            appid_text = appid_content[0].get("plain_text", "")
            if appid_text:
                appid_map[appid_text] = page_id

    return appid_map


# === Notion 集成 ===
def get_game_achievements(appid):
    url = f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1?appid={appid}&key={os.getenv('STEAM_API_KEY')}&steamid={os.getenv('STEAM_ID')}&l=schinese"
    for attempt in range(1, STEAM_RETRY_TIMES + 1):
        try:
            response = requests.get(url, timeout=STEAM_TIMEOUT)
            data = response.json().get("playerstats", {})
            achievements = data.get("achievements", [])

            return achievements

        except Exception as e:
            print(f"⚠️ 游戏 {appid} 成就获取失败 (尝试 {attempt}/{STEAM_RETRY_TIMES}): {str(e)}")
            time.sleep(REQUEST_DELAY * attempt)
    return {}
    pass


def calculate_achievement_rate(achievements):
    """
    计算游戏成就完成率

    Args:
        achievements: 从Steam API获取的成就数据列表

    Returns:
        dict: 包含完成率统计信息的字典
    """
    if not achievements:
        return {
            "total": 0,
            "unlocked": 0,
            "rate": 0.0,
            "percentage": "0%"
        }

    total_achievements = len(achievements)
    unlocked_achievements = sum(1 for ach in achievements if ach.get("achieved", 0) == 1)
    completion_rate = unlocked_achievements / total_achievements if total_achievements > 0 else 0

    return {
        "total": total_achievements,
        "unlocked": unlocked_achievements,
        "rate": completion_rate,
        "percentage": f"{completion_rate * 100:.1f}%"
    }


def import_to_notion(games):
    """导入数据到Notion（含详细状态跟踪）"""
    ensure_notion_database_columns()
    print(f"\n准备导入 {len(games)} 个游戏...")

    # 初始化统计变量
    success_count = 0
    fail_count = 0
    skipped_count = 0
    start_time = time.time()

    # 获取原数据
    origin_data = notion.search(filter={"value": "page", "property": "object"})["results"]
    appid_map_page_id = create_store_url_map_for_pages(origin_data)

    # 创建状态表格展示
    print("\n导入状态实时更新：")
    print("+" + "-" * 92 + "+")
    print(f"| {'状态':^8} | {'游戏名':^40} | {'时长':^5} | {'进度':^6} | {'耗时':^7} |")
    print("+" + "-" * 92 + "+")

    for idx, game in enumerate(games, 1):
        appid = game["appid"]
        hours = round(game.get("playtime_forever", 0) / 60, 1)
        game_name = game.get("name", f"未知游戏 ({appid})")[:40]
        elapsed = f"{time.time() - start_time:.1f}s"
        progress = f"{idx}/{len(games)}"

        try:
            display_progress_bar(idx - 1, len(games), prefix='进度:', suffix=f'处理中 {idx}/{len(games)}')
            details = get_game_details_with_cover(appid)
            achievements = get_game_achievements(appid)
            achievement_rate = calculate_achievement_rate(achievements)
            if not details.get("cover_url"):
                continue
            properties = {
                "游戏名": {"title": [{"text": {"content": details.get("name", f"未知游戏 {appid}")[:200]}}]},

                "游玩时长": {"number": max(0, round(game.get("playtime_forever", 0) / 60, 1))},

                '成就进度': {'number': achievement_rate['rate']},

                "最后游玩": {"date": {"start": timestamp_to_iso(game.get("rtime_last_played"))}}
                if game.get("rtime_last_played") else None,

                "标签": {"multi_select": [{"name": tag} for tag in details.get("zh_tags", [])]}
                if details.get("zh_tags") else None,

                "开发商": {"rich_text": [{"text": {"content": ", ".join(details["developers"])[:200]}}]}
                if details.get("developers") else None,

                "appid": {"rich_text": [{"text": {"content": f"{appid}"}}]},
                "数据更新时间": {"date": {"start": timestamp_to_iso(int(time.time()))}},
            }
            icon_or_cover = {
                'type': 'external',
                'external': {
                    'url': details.get("cover_url", "")
                }
            }

            # 导入尝试
            for attempt in range(1, NOTION_RETRY_TIMES + 1):
                try:
                    if str(appid) in appid_map_page_id.keys():
                        notion.pages.update(page_id=appid_map_page_id[str(appid)], in_trash=True)
                    notion.pages.create(
                        parent={"database_id": os.getenv("NOTION_DATABASE_ID")},
                        properties={k: v for k, v in properties.items() if v is not None},
                        icon=icon_or_cover,
                        cover=icon_or_cover
                    )
                    status = "✅ 成功"
                    success_count += 1
                    break
                except requests.exceptions.ConnectionError:
                    if attempt == NOTION_RETRY_TIMES:
                        status = "❌ 失败(连接)"
                        fail_count += 1
                    else:
                        time.sleep(NOTION_DELAY * attempt)
                except Exception as e:
                    status = f"❌ 失败({str(e)})"
                    fail_count += 1
                    break

        except Exception as e:
            status = f"⚠️ 跳过({str(e)[:10]}...)"
            skipped_count += 1

        # 实时更新状态行
        print(f"| {status:^8} | {game_name:<40} | {hours:^5} | {progress:^6} | {elapsed:^7} |")
        time.sleep(NOTION_DELAY)

    # 最终统计
    print("+" + "-" * 92 + "+")
    print(f"| {'完成情况':^90} |")
    print("+" + "-" * 92 + "+")
    print(
        f"| 成功: {success_count:^5} | 失败: {fail_count:^5} | 跳过: {skipped_count:^5} | 总计: {len(games):^5} | 耗时: {time.time() - start_time:.1f}s |")
    print("+" + "-" * 92 + "+")

    # 配置画廊视图
    try:
        notion.databases.update(
            database_id=os.getenv("NOTION_DATABASE_ID"),
            views={
                "游戏画廊": {
                    "type": "gallery",
                    "gallery": {
                        "cover": {"type": "external", "external": {"property": "封面链接"}},
                        "card_size": "medium",
                        "properties": ["游戏名", "发行日期"]
                    }
                }
            }
        )
        print("\n🎉 已自动配置画廊视图")
    except Exception as e:
        print(f"\n⚠️ 画廊视图配置失败: {str(e)}")


def ensure_notion_database_columns():
    """确保Notion数据库包含所有需要的列"""
    try:
        db_id = os.getenv("NOTION_DATABASE_ID")
        db = notion.databases.retrieve(database_id=db_id)

        # 检查是否已有商店链接列
        if "商店链接" not in db["properties"]:
            notion.databases.update(
                database_id=db_id,
                properties={
                    "商店链接": {
                        "url": {}  # 定义URL类型列
                    }
                }
            )
            print("✅ 已添加'商店链接'列到Notion数据库")
    except Exception as e:
        print(f"⚠️ 数据库结构检查失败: {str(e)}")


# === 主程序 ===
if __name__ == "__main__":
    print("\n=== Steam游戏库同步工具 ===")

    try:
        # 获取所有游戏
        print("\n正在从Steam获取游戏库数据...")
        steam_games = get_steam_games()

        if not steam_games:
            print("没有找到可导入的游戏")
            exit()

        print(f"共找到 {len(steam_games)} 款游戏 (按游玩时长排序)")

        # 让用户选择要导入的游戏
        selected_games = select_games_to_import(steam_games)

        if not selected_games:
            print("没有选择任何游戏，退出程序")
            exit()

        print(f"\n即将导入以下 {len(selected_games)} 个游戏:")
        for idx, game in enumerate(selected_games, 1):
            hours = round(game.get("playtime_forever", 0) / 60, 1)
            game_name = game.get("name", f"未知游戏 ({game['appid']})")
            print(f"{idx:3}. {game_name[:50]:50} ({hours}小时)")

        # confirm = input("\n确认导入 (Y/N)? ").strip().lower()
        confirm = 'y'
        if confirm != 'y':
            print("取消导入")
            exit()

        # 开始导入
        import_to_notion(selected_games)

    except Exception as e:
        print(f"\n!!! 程序异常: {str(e)}")
    finally:
        print("\n=== 操作完成 ===")
