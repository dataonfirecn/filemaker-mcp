/**
 * FileMaker 时间戳（`MM/DD/YYYY HH:MM:SS`，或 ISO `YYYY-MM-DD[T ]HH:MM:SS`）统一显示为
 * `YYYY-MM-DD HH:mm`；无法识别的值原样返回，空值返回空字符串。
 */
export function formatStamp(raw: unknown): string {
  const text = String(raw ?? "").trim();
  if (!text) return "";
  const us = /^(\d{1,2})\/(\d{1,2})\/(\d{4})(?: (\d{1,2}):(\d{2})(?::\d{2})?)?$/.exec(text);
  if (us) {
    const [, month, day, year, hour, minute] = us;
    const date = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
    return hour === undefined ? date : `${date} ${hour.padStart(2, "0")}:${minute}`;
  }
  const iso = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2})?)?/.exec(text);
  if (iso) return iso[2] ? `${iso[1]} ${iso[2]}` : iso[1];
  return text;
}
