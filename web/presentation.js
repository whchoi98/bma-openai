const validAccount = (value) => typeof value === "string" && /^\d{12}$/.test(value);

export function displayAccountId(value) {
  return validAccount(value) ? "*********" + value.slice(-3) : "확인 필요";
}

const digitGap = "[\\s*_`-]*";
const accountLabel = "(?:\\baccount(?:[\\s_]*id)?|계정(?:\\s*(?:ID|아이디))?)[\\s:：=\"']*(?:\\*{1,3}|_{1,3}|`{1,3})?[ \\t]*";

export function restoreAccountMasks(value) {
  return String(value).replace(/\uE000(\d{3}|MASK)\uE001/g,
    (_, suffix) => suffix === "MASK" ? "*********" : "*********" + suffix);
}

export function maskAccountIds(value, accounts, { markers = false, partial = false, strict = false } = {}) {
  let text = String(value);
  for (const account of accounts) {
    if (!validAccount(account)) continue;
    const replacement = `\uE000${account.slice(-3)}\uE001`;
    if (strict) text = text.replaceAll(account, replacement);
    const pattern = account.split("").join(digitGap);
    text = text.replace(new RegExp(`(?<![A-Za-z0-9])${pattern}(?![A-Za-z0-9])`, "g"), () => replacement);
    for (let length = 11; length >= 1; length--) {
      const prefix = account.slice(0, length).split("").join(digitGap);
      const hidden = "\uE000MASK\uE001";
      const stop = "(?![ \\t*_`-]*\\d)";
      text = text.replace(new RegExp(`(${accountLabel})${prefix}${stop}`, "gi"),
        (_, label) => label + hidden);
      if (partial && length >= 4) {
        text = text.replace(new RegExp(`(?<![A-Za-z0-9_-])${prefix}${stop}(?=[\\s\"'*_\`]*(?:$|[\\r\\n]|<\\/))`, "g"),
          () => hidden);
      }
    }
  }
  return markers ? text : restoreAccountMasks(text);
}

export function hidePendingAccount(markdown, accounts) {
  // A streamed account number must not appear one digit at a time before it is masked.
  const valid = [...accounts].filter(validAccount);
  if (valid.some((account) => markdown.endsWith(account))) return markdown;
  for (const account of valid) {
    for (let length = 11; length > 0; length--) {
      if (markdown.endsWith(account.slice(0, length))) {
        const previous = markdown[markdown.length - length - 1];
        if (previous && /[A-Za-z0-9_-]/.test(previous)) continue;
        return markdown.slice(0, -length) + "Account ID";
      }
    }
  }
  return markdown;
}

export function cleanNarrative(value) {
  return String(value)
    .replaceAll("오리건", "오레곤")
    .replace(/[ \t]*[\u00b7\u2022\u2027\u2219\u2014][ \t]*/g, ", ");
}

export function cleanMarkdownProse(value) {
  // Keep identifiers in code and URLs exact while cleaning narrative punctuation.
  const source = String(value);
  const protectedText = /(`+)[\s\S]*?\1|https?:\/\/[^\s)>]+/g;
  let result = "", offset = 0;
  for (const match of source.matchAll(protectedText)) {
    result += cleanNarrative(source.slice(offset, match.index)) + match[0];
    offset = match.index + match[0].length;
  }
  return result + cleanNarrative(source.slice(offset));
}

export function displayModel(model) {
  return typeof model === "string" && /(?:^|\.)gpt-[\w.-]*luna(?:$|[.-])/.test(model)
    ? "Luna" : model || "모델 호출 없음";
}
