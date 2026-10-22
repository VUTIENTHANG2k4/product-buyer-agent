/** Khóa TanStack Query tập trung, để mutation làm mới đúng nhóm dữ liệu. */
export const queryKeys = {
  health: ['health'] as const,
  lists: {
    all: ['lists'] as const,
    detail: (id: number) => ['lists', id] as const,
  },
  alerts: {
    all: ['alerts'] as const,
  },
  products: {
    all: ['products'] as const,
    detail: (id: number) => ['products', id] as const,
    priceHistory: (id: number, days: number) => ['products', id, 'price-history', days] as const,
    summary: ['products', 'summary'] as const,
  },
  compare: (ids: readonly number[]) => ['compare', ...ids] as const,
  conversations: {
    all: ['conversations'] as const,
    messages: (id: number) => ['conversations', id, 'messages'] as const,
  },
  admin: {
    sources: ['admin', 'sources'] as const,
    runs: (filters: Record<string, unknown>) => ['admin', 'runs', filters] as const,
    runsAll: ['admin', 'runs'] as const,
    challenge: (runId: number) => ['admin', 'challenge', runId] as const,
  },
}
