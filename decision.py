"""多选项的文本解析和随机规则，仅依赖 Python 标准库。"""

import random
import re


BOTH_ANSWER = "两者皆有可能，这就是答案"
MAX_REASON_LENGTH = 15
DEFAULT_REPLY_TEMPLATES = (
    '俺寻思"[x]"是对的。',
    '显然"[x]"更好。',
    '那必然是 "[x]"',
    '这还用选？"[x]"',
    '有一说一，"[x]" 完胜',
    '不懂就选 "[x]"，懂了还是选 "[x]"',
    '正常人都知道选 "[x]"',
    '但凡犹豫一秒都是对 "[x]" 的不尊重',
    '别问，问就是 "[x]"',
    '我宣布 "[x]" 获胜',
    '经过严谨论证，答案是 "[x]"',
    '经研究决定，选 "[x]"',
    '科学证明 "[x]" 比较好',
    '数据表明："[x]"',
    '祖宗之法不可变，选 "[x]"',
    '古人云：选 "[x]"',
    '老祖宗传下来的规矩就是 "[x]"',
    '天意如此，"[x]"',
    '天命在 "[x]"',
    '顺天应人，当选 "[x]"',
    '"[x]"，无需多言',
    '"[x]"，唯一指定答案',
    '"[x]"，不接受反驳',
    '"[x]"，已经赢了',
    '"[x]"，含金量还在上升',
    '"[x]"，这把真没得说',
    '"[x]"，优势在我',
    '"[x]"，大抵是极好的',
    '"[x]"，颇有一种正确答案的美',
    '"[x]"，一眼丁真，鉴定为优',
    '"[x]"，好似',
    '"[x]"，他真的，我哭死',
    '"[x]"，我只能说懂的都懂',
    '"[x]"，不选的人有难了',
    '"[x]"，选了不一定赢，不选一定后悔',
    '"[x]"，包对的',
    '"[x]"，包赢的',
    '"[x]"，这波属于版本答案',
    '"[x]"，当前环境唯一解',
    '"[x]"，属于是版本陷阱的反面',
    '"[x]"，闭着眼选都不会错',
    '"[x]"，这辈子有了',
    '"[x]"，输了算我的',
    '听哥一句，"[x]"',
    '相信我，"[x]"',
    '哥们不骗哥们，选 "[x]"',
    '我一般不劝人，但这次真得 "[x]"',
    '你可以不信我，但你得信 "[x]"',
    '选别的我不好评价，选 "[x]" 我只能说有品',
    '你问我支持谁，我只能说 "[x]"',
    '一个是其他选项，一个是 "[x]"，这怎么选？',
    '左边是错误答案，右边是错误答案，"[x]" 是正确答案',
    '世间万物皆有两面，唯独 "[x]" 是标准答案',
    '如果 "[x]" 有一百万个支持者，我是其中一个',
    '如果 "[x]" 只有一个支持者，那就是我',
    '如果没人选 "[x]"，那说明我已经不在了',
    '我不是说 "[x]" 最好，我只是说其他的都不如 "[x]"',
    '公平起见，我选择无条件偏袒 "[x]"',
    '理性分析半天，最后还是 "[x]"',
    '感性上选 "[x]"，理性上也选 "[x]"',
    '排除所有错误答案以后，剩下的就是 "[x]"',
    '先不谈事实，我觉得 "[x]" 赢了',
    '抛开其他选项不谈，"[x]" 就是最好的',
    '虽然没有任何依据，但我非常确信 "[x]"',
    '证据暂时没有，结论先定 "[x]"',
    '论证以后再补，先选 "[x]"',
    '原因很复杂，简单来说就是 "[x]"',
    '为什么选 "[x]"？因为我喜欢',
    '为什么 "[x]" 更好？因为它是 "[x]"',
    '"[x]" 好在哪？好就好在它比较好',
    '"[x]" 为什么赢？因为没输',
    '我寻思半天，还是觉得 "[x]" 比较像答案',
    '看到 "[x]" 的第一眼，我就知道事情并不简单',
    '此时一位 "[x]" 悄悄路过并拿下胜利',
    '"[x]"：优势在我',
    '"[x]"：还有高手？',
    '"[x]"：我来组成答案',
    '"[x]"：这把高端局',
    '不是哥们，真有人不选 "[x]" 啊？',
    '不会真有人觉得 "[x]" 以外还有答案吧',
    '都 2026 年了还有人不选 "[x]"',
    '不是 "[x]" 选不起，而是其他选项更没有性价比',
    '"[x]" 可能不是最强的，但一定是我最想让你选的',
    '我给不了你客观评价，因为 "[x]" 已经把我收买了',
    '本次投票坚持公开、公平、公正，所以我投 "[x]"',
    '民主投票结果：我一票决定 "[x]"',
    '全票通过，一票赞成，零票反对，选 "[x]"',
    '经组委会一致决定——组委会只有我——选 "[x]"',
    '经专家会诊，专家就是我，建议 "[x]"',
    '我掐指一算，你命里缺 "[x]"',
    '今日宜："[x]"；忌：选别的',
    '黄历上写了，今天适合 "[x]"',
    '占卜结果显示 "[x]"，不准也得准',
    '这不是选择题，这是送分题，答案 "[x]"',
    '题目已经把答案写脸上了："[x]"',
    'A、B、C、D 都不用看，选 "[x]"',
    '遇事不决，"[x]"',
    '量子力学，"[x]"',
    '遇事不决量子力学，选择困难直接 "[x]"',
    '我愿称 "[x]" 为本题最优解',
    '"[x]"，启动！',
    '"[x]"，堂堂登场',
    '"[x]"，堂堂胜利',
)


def format_answer(answer: str, templates: object) -> str:
    """从含 [x] 的模板中随机选择；无有效模板时使用默认模板。"""
    candidates = []
    if isinstance(templates, (list, tuple)):
        candidates = [
            item.strip()
            for item in templates
            if isinstance(item, str) and item.strip() and "[x]" in item
        ]
    template = random.choice(candidates or DEFAULT_REPLY_TEMPLATES)
    # 已有双引号的占位符只保留一层；自定义裸占位符同样带双引号。
    return re.sub(r'"\[x\]"|“\[x\]”|\[x\]', lambda match: f'"{answer}"', template)


def fallback_reason(answer: str) -> str:
    """保留“因为xx善”格式；长选项缩写，确保原因不超过 15 字。"""
    label = re.sub(r"\s+", " ", answer).strip()
    budget = MAX_REASON_LENGTH - len("因为善")
    if len(label) > budget:
        label = label[: budget - 1] + "…"
    return f"因为{label}善"


def normalize_reason(text: object, answer: str) -> str:
    """只接受简短单行原因，不输出超长解释或模型的困难说明。"""
    fallback = fallback_reason(answer)
    if not isinstance(text, str):
        return fallback
    reason = re.sub(r"^(?:原因|理由)\s*[:：]\s*", "", text.strip())
    reason = reason.strip().strip('"“”').strip()
    if (
        not reason
        or len(reason) > MAX_REASON_LENGTH
        or "\n" in reason
        or "\r" in reason
        or any(word in reason for word in ("想不出", "想不到", "不好想", "不知道", "无法给出"))
    ):
        return fallback
    return reason


def parse_options(text: str) -> tuple[str, ...] | None:
    """接受两个或更多以“还是”或 | 分隔的非空选项。"""
    text = text.strip().rstrip("？?").strip()
    # 显式分隔符允许选项本身包含“还是”，例如“继续 | 还是算了”。
    separator = "|" if "|" in text else "还是"
    options = tuple(part.strip() for part in text.split(separator))
    if len(options) < 2 or not all(options):
        return None
    return options


def parse_natural_options(text: str) -> tuple[str, ...] | None:
    """自然问句须有“ 还是 ”，或同时含“帮我选”和“还是”。"""
    text = text.strip().rstrip("？?。.!！").strip()
    if "帮我选" in text and "还是" in text:
        # 提示词及相邻标点不属于选项；“还是”可不带空格。
        text = re.sub(r"[ \t\r\n，,：:]*帮我选[ \t\r\n，,：:]*", "", text, count=1)
        return parse_options(text)
    if " 还是 " not in text:
        return None
    # 只按带空格的触发词分隔，保留选项内部未带空格的“还是”。
    options = tuple(part.strip() for part in re.split(r"(?<= )还是(?= )", text))
    return options if len(options) >= 2 and all(options) else None


def choose_answer(options: tuple[str, ...], special_probability: int = 10) -> str | None:
    """特殊答案按整数百分比抽取，剩余概率在全部选项间严格等分。"""
    if isinstance(special_probability, bool) or not isinstance(special_probability, int):
        special_probability = 10
    probability = min(max(special_probability, 0), 100)
    # 每个选项各占 (100-p) 个等可能值，特殊分支占 p*n 个。
    count = len(options)
    roll = random.randrange(100 * count)
    special_count = probability * count
    if roll < special_count:
        return None
    return options[(roll - special_count) // (100 - probability)]
