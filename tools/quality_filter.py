"""Deterministic structural quality rules for staging records and IME units."""

import re
from collections import Counter

from tools.corpus_workflow import CJK


FILTER_VERSION = "0.3.0"
CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\x7f]")
PLACEHOLDER = re.compile(r"(?:_COUNT_|<[^>]{1,80}>|\{[^{}]{1,80}\})")
# Four or more identical wide characters, or three or more identical ASCII symbols; digits and letters are kept.
REPEATED = re.compile(r"([^\x00-\x7f])\1{3,}|([\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e])\2{2,}")
META_PREFIX = re.compile(r"^(?:记者|本报讯|原标题|来源[:：]|责任编辑)")
TRAILING_CONNECTOR = re.compile(r"(?:与|和|及|但|因为|如果|以及|将|为|并)$")
PUNCTUATION = re.compile(r"[\u2000-\u206f\u3000-\u303f\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65!-/:-@\[-`{-~]")
# Every bracket and quote takes part in the closer scan; only the count rule stays limited to the original brackets.
OPENERS = {"（": "）", "(": ")", "[": "]", "【": "】", "“": "”", "‘": "’", "《": "》", "「": "」", "『": "』", "〈": "〉"}
BRACKETS = ("（", "(", "[", "【")
CLOSER_TEXT = "”’）》」』〕】〉)]"
OPENER_TEXT = "".join(OPENERS)
END_MARKS = "，。！？；…,.!?;"
BRACKET = re.compile(r"[()（）\[\]【】“”‘’《》「」『』〈〉]")
WIDE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff01-\uff65"
CJK_SPACE = re.compile(rf"[{WIDE}] [{WIDE}]")
LIST_NUMBERING = re.compile(r"^\d{1,3}(?:[、：:]|\.(?!\d))(?!\d)")
URL_HANDLE = re.compile(r"https?://|www\.|[@＠#<>{}|]|\.(?:com|cn|net|org)(?![A-Za-z])")
SYMBOL = re.compile(r"[\u2030-\u205e\u2190-\u21ff\u2300-\u23ff\u2460-\u27bf\u2b00-\u2bff\U0001f000-\U0001faff]|\[[^\[\]]{1,8}\]")
LATIN = re.compile(r"[A-Za-z]")
DIGITS = re.compile(r"\d")
# Characters that only exist in traditional Chinese text; every one of them has a different simplified form.
TRADITIONAL_TEXT = (
    "們這個來說時會對發現麼為樣還開關覺聽寫學國華萬與東車長門問間線經過遠選風電話語課誰請論講謝證識讓變點黨龍愛從無數樂雲區網頁錢買賣貴費頭髮體應該貓"
    "鳥馬魚飛飯飲藥醫療聞報紙書錄視節劇場戲價幣匯險資產權豐歲訊認譯詩詞誤誘調談諸謀謹譜護讀讚貝負財責賢質賺贈贏趙趕趨軍輕較輛輸轉辦農運進達違遙遺鄉鄭"
    "醜鐘鋼錯鍵鎮鏡鐵鑑閃閉閒閱陝陣陽隊階際雜雞離難靈靜響頂項順須頓額顏題願類顧養餘驅驗廠廣廳廢彎張強當復徵懷懸慶憶憲戰擊擴擔據擇擾敵斷曬極構槍標樹橋"
    "機檢歡殘殺氣決涼淨減測溫準濃濕濟滿滾燈營爭爾獨獲獻環畫異疊盡監盤眾瞭礦確禮稱種穩積窮競筆範築簡糧紅紀約納級紛細組終結絕統絲綁綜綠維綱緊編緣練縣縮"
    "總織繪續纖羅義習職聯聲肅脅脈脫腳腸臟臨興舉舊艦蘇蘭處號虧衛衝補裝裡製複規親觀計訂訓記討許診評試詳誠諾謂謊議貢賀貼貿賓賞賦購賽贊贖跡踐輝輩輪轟辭連"
    "週遊遜遞適遲遼邊鄰釀釋鉤銀銘銳銷鋒錦鍊鍋鎖鑰鑽闊陰陳陸隨隸雖雙飾餅鬆鬥鬧鮮鳴鴻麗麥麵黃齊齒龜珰訴藍塊餓鉄慮迴幫檔戸圖寧條紹郵員敗歎單歩蹟籤焼県髪"
    "懶動將壽兒卻頃逹業優証佔捲醬鴨覚様並見樓蝦嘗毎賤鉑務豈實內爲兩帶幾衞韓歐湯湊給徳荳別説倆豊増髙恵敍璿譌幹圍夠彆徑悽惡斂暉潛澀燄瘋睏祕甦暱姪洩妳裏"
    "寳峯喫嚐鉛島寛歳満凪榊楪辻畑畠咲喰峠渋瑠嶋譲鰈鮑鮪鯛顯沒渾瓊瑪璽攝殮毀獷嶽巖煕靑蓭唸佈勳囉馀単嘆嗎嗩嘰嚇麽嘍嚕囑囪圇團園圓塵墊墜墮墻墳墾備媽後隻"
    "臺"
)
FOREIGN_LETTER = re.compile(r"(?![0-9A-Za-z\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])[^\W\d_]", re.UNICODE)
RARE_CJK = re.compile(r"[\uf900-\ufaff\U00020000-\U0003ffff]")
TRADITIONAL = re.compile(f"[{TRADITIONAL_TEXT}]")
TRAILING_CLOSER = re.compile(r"[，。！？；…,.!?;]+[”’）》」』〕】〉)\]]+$")


def unmatched_closer(text):
    """Report a closer that nothing opens; a closer after a clause mark may close an earlier unit."""
    core = TRAILING_CLOSER.sub("", text)
    stack = []
    for char in core:
        if char in OPENERS:
            stack.append(OPENERS[char])
        elif char in CLOSER_TEXT:
            if not stack or stack[-1] != char:
                return True
            stack.pop()
    return False


def classify(row, min_chars=4, max_chars=160):
    text = row.get("text", "") if isinstance(row, dict) else ""
    flags = []
    if not isinstance(text, str):
        flags.append("text_not_string")
        text = ""
    if "\n" in text or "\r" in text:
        flags.append("internal_newline")
    if "\\n" in text:
        flags.append("escaped_newline")
    if CONTROL.search(text):
        flags.append("control_character")
    if PLACEHOLDER.search(text):
        flags.append("placeholder")
    if len(text) < min_chars:
        flags.append("too_short")
    if len(text) > max_chars:
        flags.append("too_long")
    if len(CJK.findall(text)) < 2:
        flags.append("no_chinese")
    if REPEATED.search(text):
        flags.append("repeated_character")
    if text and len(PUNCTUATION.findall(text)) / len(text) > 0.45:
        flags.append("punctuation_heavy")
    if META_PREFIX.search(text):
        flags.append("metadata_prefix")
    if TRAILING_CONNECTOR.search(text):
        flags.append("trailing_connector")
    for opener in BRACKETS:
        if text.count(opener) != text.count(OPENERS[opener]):
            flags.append("unmatched_bracket")
            break
    if text and (text[0] in CLOSER_TEXT or text[0] in END_MARKS):
        flags.append("leading_closer")
    if text and text[-1] in OPENER_TEXT:
        flags.append("trailing_opener")
    if CJK_SPACE.search(text):
        flags.append("cjk_space")
    if BRACKET.search(text) and unmatched_closer(text):
        flags.append("unmatched_closer")
    if LIST_NUMBERING.search(text):
        flags.append("list_numbering")
    if URL_HANDLE.search(text):
        flags.append("url_or_handle")
    if SYMBOL.search(text):
        flags.append("symbol_or_emoticon")
    if FOREIGN_LETTER.search(text):
        flags.append("other_scripts")
    if RARE_CJK.search(text):
        flags.append("rare_cjk")
    if TRADITIONAL.search(text):
        flags.append("traditional_chars")
    if text and len(LATIN.findall(text)) / len(text) > 0.3:
        flags.append("latin_heavy")
    if text and len(DIGITS.findall(text)) / len(text) > 0.4:
        flags.append("digit_heavy")
    hard = {"text_not_string", "control_character", "placeholder", "too_short", "too_long", "no_chinese",
            "repeated_character", "leading_closer", "trailing_opener", "cjk_space", "unmatched_closer",
            "list_numbering", "url_or_handle", "symbol_or_emoticon", "other_scripts", "rare_cjk", "traditional_chars",
            "latin_heavy", "digit_heavy"}
    status = "rejected" if hard.intersection(flags) else "review" if flags else "accepted"
    return {"status": status, "flags": sorted(set(flags)), "filter_version": FILTER_VERSION}


def filter_rows(rows, accepted, review, rejected, filter_out, min_chars=4, max_chars=160):
    counts = Counter()
    flags = Counter()
    sources = Counter()
    for row in rows:
        quality = classify(row, min_chars, max_chars)
        output = {**row, "quality": quality}
        status = quality["status"]
        counts[status] += 1
        sources[row.get("source_id", "unknown")] += 1
        flags.update(quality["flags"])
        target = accepted if status == "accepted" else review if status == "review" else rejected
        line = __import__("json").dumps(output, ensure_ascii=False, sort_keys=True) + "\n"
        target.write(line)
        if status != "accepted":
            filter_out.write(line)
    return {"counts": dict(sorted(counts.items())), "flags": dict(sorted(flags.items())),
            "sources": dict(sorted(sources.items())), "filter_version": FILTER_VERSION}
