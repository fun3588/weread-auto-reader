# idgen.py 微信读书哈希 id 生成算法（逆向自 web 前端模块156，2026-08-08 实测验证）
#
# 背景：read 请求的字段 b/c 使用前端加密：
#   b = bookId（原始哈希形态，不编码）
#   c = e(chapterUid)，其中 e() 为模块156 的导出函数
# 算法（已用三体 ci=4 真实抓包验证：e(89) == '764323602597647966b7a1c'，read 返回 succ=1）：
#   1. digest = md5(输入字符串) 的 hex
#   2. result = digest[:3]
#   3. 编码输入：
#      - 纯数字：每 9 位一组 parseInt 后转 hex，标记位 '3'，组间以 'g' 分隔
#      - 非数字：逐字符 charCodeAt 转 hex 拼成一串，标记位 '4'
#   4. result += '2' + digest[-2:]
#   5. 逐段追加：段长度(1~2位hex，1位补0) + 段内容；段间加 'g'
#   6. result 不足 20 位时用 digest 前缀补齐
#   7. result += md5(result)[:3] 作为校验位
# v() 为校验函数：末 3 位 == md5(前部)[:3]。
import re
import hashlib


def e(value):
    """生成 23 位哈希 id（bookId 用原始值，chapterId 用 chapterUid）"""
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return value
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    result = digest[:3]

    if re.fullmatch(r"\d*", value):
        parts = []
        for i in range(0, len(value), 9):
            parts.append(format(int(value[i:i + 9]), "x"))
        result += "3"
    else:
        parts = ["".join(format(ord(c), "x") for c in value)]
        result += "4"

    result += "2" + digest[-2:]

    for i, part in enumerate(parts):
        ln = format(len(part), "x")
        if len(ln) == 1:
            ln = "0" + ln
        result += ln + part
        if i < len(parts) - 1:
            result += "g"

    if len(result) < 20:
        result += digest[:20 - len(result)]

    result += hashlib.md5(result.encode("utf-8")).hexdigest()[:3]
    return result


def v(cid):
    """校验 23 位哈希 id：末 3 位 == md5(前部)[:3]"""
    if len(cid) <= 3:
        return False
    body, tail = cid[:-3], cid[-3:]
    return hashlib.md5(body.encode("utf-8")).hexdigest()[:3] == tail


if __name__ == "__main__":
    print("e(89) =", e(89), "校验:", v(e(89)))
    print("期望   = 764323602597647966b7a1c")
    assert e(89) == "764323602597647966b7a1c"
    assert v("764323602597647966b7a1c")
    print("算法验证通过")
