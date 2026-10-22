const MAX_INT4 = 2 ** 31 - 1

/** `:conversationId` hợp lệ là số nguyên dương trong miền khóa chính; còn lại coi là không tồn tại. */
export function parseConversationId(raw: string | undefined): number | null {
  if (raw === undefined || !/^\d+$/.test(raw)) return null
  const value = Number(raw)
  return value >= 1 && value <= MAX_INT4 ? value : null
}
