from typing import Any, Dict, List


def bangumi_ui() -> List[Dict[str, Any]]:
    """
    番剧 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "3", "Text": "追番人数"},
                {"Value": "0", "Text": "更新时间"},
                {"Value": "4", "Text": "最高评分"},
                {"Value": "2", "Text": "播放数量"},
                {"Value": "5", "Text": "开播时间"},
            ],
        },
        {
            "Id": "season_version",
            "Text": "类型",
            "Options": [
                {"Value": "1", "Text": "正片"},
                {"Value": "2", "Text": "电影"},
                {"Value": "3", "Text": "其他"},
            ],
        },
        {
            "Id": "spoken_language_type",
            "Text": "配音",
            "Options": [
                {"Value": "1", "Text": "原声"},
                {"Value": "2", "Text": "中文配音"},
            ],
        },
        {
            "Id": "area",
            "Text": "地区",
            "Options": [
                {"Value": "2", "Text": "日本"},
                {"Value": "3", "Text": "美国"},
                {
                    "Value": "1,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70",
                    "Text": "其他",
                },
            ],
        },
        {
            "Id": "is_finish",
            "Text": "状态",
            "Options": [
                {"Value": "1", "Text": "完结"},
                {"Value": "0", "Text": "连载"},
            ],
        },
        {
            "Id": "_copyright",
            "Text": "版权",
            "Options": [
                {"Value": "3", "Text": "独家"},
                {"Value": "1,2,4", "Text": "其他"},
            ],
        },
        {
            "Id": "season_month",
            "Text": "季度",
            "Options": [
                {"Value": "1", "Text": "1月"},
                {"Value": "4", "Text": "4月"},
                {"Value": "7", "Text": "7月"},
                {"Value": "10", "Text": "10月"},
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10010", "Text": "原创"},
                {"Value": "10011", "Text": "动画"},
                {"Value": "10012", "Text": "漫画"},
                {"Value": "10013", "Text": "游戏改"},
                {"Value": "10102", "Text": "特摄"},
                {"Value": "10015", "Text": "布袋戏"},
                {"Value": "10016", "Text": "热血"},
                {"Value": "10017", "Text": "穿越"},
                {"Value": "10018", "Text": "奇幻"},
                {"Value": "10020", "Text": "战斗"},
                {"Value": "10021", "Text": "搞笑"},
                {"Value": "10022", "Text": "日常"},
                {"Value": "10023", "Text": "科幻"},
                {"Value": "10024", "Text": "萌系"},
                {"Value": "10025", "Text": "治愈"},
                {"Value": "10026", "Text": "校园"},
                {"Value": "10027", "Text": "少儿"},
                {"Value": "10028", "Text": "泡面"},
                {"Value": "10029", "Text": "恋爱"},
                {"Value": "10030", "Text": "少女"},
                {"Value": "10031", "Text": "魔法"},
                {"Value": "10032", "Text": "冒险"},
                {"Value": "10033", "Text": "历史"},
                {"Value": "10034", "Text": "架空"},
                {"Value": "10035", "Text": "机战"},
                {"Value": "10036", "Text": "神魔"},
                {"Value": "10037", "Text": "声控"},
                {"Value": "10038", "Text": "运动"},
                {"Value": "10039", "Text": "励志"},
                {"Value": "10040", "Text": "音乐"},
                {"Value": "10041", "Text": "推理"},
                {"Value": "10042", "Text": "社团"},
                {"Value": "10043", "Text": "智斗"},
                {"Value": "10044", "Text": "催泪"},
                {"Value": "10045", "Text": "美食"},
                {"Value": "10046", "Text": "偶像"},
                {"Value": "10047", "Text": "乙女"},
                {"Value": "10048", "Text": "职场"},
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'bangumi'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui


def guo_ui() -> List[Dict[str, Any]]:
    """
    国创 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "3", "Text": "追番人数"},
                {"Value": "0", "Text": "更新时间"},
                {"Value": "4", "Text": "最高评分"},
                {"Value": "2", "Text": "播放数量"},
                {"Value": "5", "Text": "开播时间"},
            ],
        },
        {
            "Id": "season_version",
            "Text": "类型",
            "Options": [
                {"Value": "1", "Text": "正片"},
                {"Value": "2", "Text": "电影"},
                {"Value": "3", "Text": "其他"},
            ],
        },
        {
            "Id": "is_finish",
            "Text": "状态",
            "Options": [
                {"Value": "1", "Text": "完结"},
                {"Value": "0", "Text": "连载"},
            ],
        },
        {
            "Id": "copyright",
            "Text": "版权",
            "Options": [
                {"Value": "3", "Text": "独家"},
                {"Value": "1,2,4", "Text": "其他"},
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10010", "Text": "原创"},
                {"Value": "10011", "Text": "动画"},
                {"Value": "10012", "Text": "漫画"},
                {"Value": "10013", "Text": "游戏改"},
                {"Value": "10014", "Text": "动态漫"},
                {"Value": "10015", "Text": "布袋戏"},
                {"Value": "10016", "Text": "热血"},
                {"Value": "10018", "Text": "奇幻"},
                {"Value": "10019", "Text": "玄幻"},
                {"Value": "10020", "Text": "战斗"},
                {"Value": "10021", "Text": "搞笑"},
                {"Value": "10078", "Text": "武侠"},
                {"Value": "10022", "Text": "日常"},
                {"Value": "10023", "Text": "科幻"},
                {"Value": "10024", "Text": "萌系"},
                {"Value": "10025", "Text": "治愈"},
                {"Value": "10026", "Text": "校园"},
                {"Value": "10027", "Text": "少儿"},
                {"Value": "10028", "Text": "泡面"},
                {"Value": "10029", "Text": "恋爱"},
                {"Value": "10030", "Text": "少女"},
                {"Value": "10031", "Text": "魔法"},
                {"Value": "10032", "Text": "冒险"},
                {"Value": "10033", "Text": "历史"},
                {"Value": "10034", "Text": "架空"},
                {"Value": "10035", "Text": "机战"},
                {"Value": "10036", "Text": "神魔"},
                {"Value": "10037", "Text": "声控"},
                {"Value": "10038", "Text": "运动"},
                {"Value": "10039", "Text": "励志"},
                {"Value": "10040", "Text": "音乐"},
                {"Value": "10041", "Text": "推理"},
                {"Value": "10042", "Text": "社团"},
                {"Value": "10043", "Text": "智斗"},
                {"Value": "10044", "Text": "催泪"},
                {"Value": "10045", "Text": "美食"},
                {"Value": "10046", "Text": "偶像"},
                {"Value": "10047", "Text": "乙女"},
                {"Value": "10048", "Text": "职场"},
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'guo'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui


def documentary_ui() -> List[Dict[str, Any]]:
    """
    纪录片 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "2", "Text": "播放数量"},
                {"Value": "4", "Text": "最高评分"},
                {"Value": "0", "Text": "更新时间"},
                {"Value": "6", "Text": "上映时间"},
                {"Value": "1", "Text": "弹幕数量"},
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10033", "Text": "历史"},
                {"Value": "10045", "Text": "美食"},
                {"Value": "10065", "Text": "人文"},
                {"Value": "10066", "Text": "科技"},
                {"Value": "10067", "Text": "探险"},
                {"Value": "10068", "Text": "宇宙"},
                {"Value": "10069", "Text": "萌宠"},
                {"Value": "10070", "Text": "社会"},
                {"Value": "10071", "Text": "动物"},
                {"Value": "10072", "Text": "自然"},
                {"Value": "10073", "Text": "医疗"},
                {"Value": "10074", "Text": "军事"},
                {"Value": "10064", "Text": "灾难"},
                {"Value": "10075", "Text": "罪案"},
                {"Value": "10076", "Text": "神秘"},
                {"Value": "10077", "Text": "旅行"},
                {"Value": "10038", "Text": "运动"},
                {"Value": "-10", "Text": "电影"},
            ],
        },
        {
            "Id": "producer_id",
            "Text": "出品",
            "Options": [
                {"Value": "4", "Text": "央视"},
                {"Value": "1", "Text": "BBC"},
                {"Value": "7", "Text": "探索频道"},
                {"Value": "14", "Text": "国家地理"},
                {"Value": "2", "Text": "NHK"},
                {"Value": "6", "Text": "历史频道"},
                {"Value": "8", "Text": "卫视"},
                {"Value": "9", "Text": "自制"},
                {"Value": "5", "Text": "ITV"},
                {"Value": "3", "Text": "SKY"},
                {"Value": "10", "Text": "ZDF"},
                {"Value": "11", "Text": "合作机构"},
                {"Value": "12", "Text": "国内其他"},
                {"Value": "13", "Text": "国外其他"},
                {"Value": "15", "Text": "索尼"},
                {"Value": "16", "Text": "环球"},
                {"Value": "17", "Text": "派拉蒙"},
                {"Value": "18", "Text": "华纳"},
                {"Value": "19", "Text": "迪士尼"},
                {"Value": "20", "Text": "HBO"},
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'documentary'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui


def tv_ui() -> List[Dict[str, Any]]:
    """
    电视剧 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "2", "Text": "播放数量"},
                {"Value": "0", "Text": "更新时间"},
                {"Value": "1", "Text": "弹幕数量"},
                {"Value": "4", "Text": "最高评分"},
                {"Value": "3", "Text": "追剧人数"},
            ],
        },
        {
            "Id": "area",
            "Text": "地区",
            "Options": [
                {"Value": "1,6,7", "Text": "中国"},
                {"Value": "2", "Text": "日本"},
                {"Value": "3", "Text": "美国"},
                {"Value": "4", "Text": "英国"},
                {
                    "Value": "5,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70",
                    "Text": "其他",
                },
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10050", "Text": "剧情"},
                {"Value": "10084", "Text": "情感"},
                {"Value": "10021", "Text": "搞笑"},
                {"Value": "10057", "Text": "悬疑"},
                {"Value": "10080", "Text": "都市"},
                {"Value": "10061", "Text": "家庭"},
                {"Value": "10081", "Text": "古装"},
                {"Value": "10033", "Text": "历史"},
                {"Value": "10018", "Text": "奇幻"},
                {"Value": "10079", "Text": "青春"},
                {"Value": "10058", "Text": "战争"},
                {"Value": "10078", "Text": "武侠"},
                {"Value": "10039", "Text": "励志"},
                {"Value": "10103", "Text": "短剧"},
                {"Value": "10023", "Text": "科幻"},
                {
                    "Value": "10086,10088,10089,10017,10083,10082,10087,10085",
                    "Text": "其他",
                },
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'tv'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui


def movie_ui() -> List[Dict[str, Any]]:
    """
    电影 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "2", "Text": "播放数量"},
                {"Value": "0", "Text": "更新时间"},
                {"Value": "6", "Text": "上映时间"},
                {"Value": "4", "Text": "最高评分"},
            ],
        },
        {
            "Id": "area",
            "Text": "地区",
            "Options": [
                {"Value": "1", "Text": "中国大陆"},
                {"Value": "6,7", "Text": "中国港台"},
                {"Value": "3", "Text": "美国"},
                {"Value": "2", "Text": "日本"},
                {"Value": "8", "Text": "韩国"},
                {"Value": "9", "Text": "法国"},
                {"Value": "4", "Text": "英国"},
                {"Value": "15", "Text": "德国"},
                {"Value": "10", "Text": "泰国"},
                {"Value": "35", "Text": "意大利"},
                {"Value": "13", "Text": "西班牙"},
                {
                    "Value": "5,11,12,14,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70",
                    "Text": "其他",
                },
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10104", "Text": "短片"},
                {"Value": "10050", "Text": "剧情"},
                {"Value": "10051", "Text": "喜剧"},
                {"Value": "10052", "Text": "爱情"},
                {"Value": "10053", "Text": "动作"},
                {"Value": "10054", "Text": "恐怖"},
                {"Value": "10023", "Text": "科幻"},
                {"Value": "10055", "Text": "犯罪"},
                {"Value": "10056", "Text": "惊悚"},
                {"Value": "10057", "Text": "悬疑"},
                {"Value": "10018", "Text": "奇幻"},
                {"Value": "10058", "Text": "战争"},
                {"Value": "10059", "Text": "动画"},
                {"Value": "10060", "Text": "传记"},
                {"Value": "10061", "Text": "家庭"},
                {"Value": "10062", "Text": "歌舞"},
                {"Value": "10033", "Text": "历史"},
                {"Value": "10032", "Text": "冒险"},
                {"Value": "10063", "Text": "纪实"},
                {"Value": "10064", "Text": "灾难"},
                {"Value": "10011", "Text": "漫画改"},
                {"Value": "10012", "Text": "小说改"},
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'movie'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui


def variety_ui() -> List[Dict[str, Any]]:
    """
    综艺 UI 生成器

    :return List: UI 配置列表
    """
    ui_data = [
        {
            "Id": "order",
            "Text": "顺序",
            "Options": [
                {"Value": "2", "Text": "最多播放"},
                {"Value": "0", "Text": "最近更新"},
                {"Value": "6", "Text": "最近上映"},
                {"Value": "4", "Text": "最高评分"},
                {"Value": "1", "Text": "弹幕数量"},
            ],
        },
        {
            "Id": "style_id",
            "Text": "风格",
            "Options": [
                {"Value": "10040", "Text": "音乐"},
                {"Value": "10090", "Text": "访谈"},
                {"Value": "10091", "Text": "脱口秀"},
                {"Value": "10092", "Text": "真人秀"},
                {"Value": "10094", "Text": "选秀"},
                {"Value": "10045", "Text": "美食"},
                {"Value": "10095", "Text": "旅游"},
                {"Value": "10098", "Text": "晚会"},
                {"Value": "10096", "Text": "演唱会"},
                {"Value": "10084", "Text": "情感"},
                {"Value": "10051", "Text": "喜剧"},
                {"Value": "10097", "Text": "亲子"},
                {"Value": "10100", "Text": "文化"},
                {"Value": "10048", "Text": "职场"},
                {"Value": "10069", "Text": "萌宠"},
                {"Value": "10099", "Text": "养成"},
            ],
        },
    ]

    ui = []
    for i in ui_data:
        data = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": j["Value"],
                },
                "text": j["Text"],
            }
            for j in i["Options"]
        ]
        ui.append(
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'variety'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": i["Text"]}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": i["Id"]},
                        "content": data,
                    },
                ],
            }
        )
    return ui
