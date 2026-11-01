const MAX_INT4 = 2 ** 31 - 1

/** Id trong đường dẫn: số nguyên dương trong miền khóa chính (≤ 2^31−1); còn lại coi là không tồn tại. */
export function parsePositiveId(raw: string | undefined): number | null {
  if (raw === undefined || !/^\d+$/.test(raw)) return null
  const value = Number(raw)
  return value >= 1 && value <= MAX_INT4 ? value : null
}
