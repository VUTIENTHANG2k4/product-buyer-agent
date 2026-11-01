import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
} from '@tanstack/react-query'
import { ApiError, apiFetch } from '@/api/client'
import { queryKeys } from '@/api/queryKeys'
import type { RequestBody, ResponseBody, Schemas } from '@/api/types'

export type Health = ResponseBody<'/api/health', 'get'>
export type SourcesResponse = ResponseBody<'/api/admin/sources', 'get'>
export type SourceView = SourcesResponse['items'][number]
export type ScrapeRunPage = ResponseBody<'/api/admin/scrape-runs', 'get'>
export type ScrapeRunView = ScrapeRunPage['items'][number]
export type ScrapeRunCreate = RequestBody<'/api/admin/scrape-runs', 'post'>
export type ChallengeView = ResponseBody<'/api/admin/scrape-runs/{run_id}/challenge', 'get'>
export type ScrapeStatus = Schemas['ScrapeStatus']

/** Chu kỳ làm mới khi còn lượt đang chạy (docs/08 §3.7). */
export const POLL_INTERVAL_MS = 3000
export const RUNS_PAGE_SIZE = 10

/** Lượt chưa kết thúc: còn thay đổi nên cần làm mới định kỳ. */
export function isActive(status: ScrapeStatus): boolean {
  return status === 'RUNNING' || status === 'PENDING'
}

export interface RunFilters {
  site: Schemas['SiteKey'] | null
  category: Schemas['Category'] | null
  status: ScrapeStatus | null
  page: number
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => apiFetch<Health>('health', { signal }),
  })
}

/** Làm mới mỗi 3 giây chừng nào lượt chạy gần nhất của một nguồn nào đó còn đang chạy. */
export function useSources() {
  return useQuery({
    queryKey: queryKeys.admin.sources,
    queryFn: ({ signal }) => apiFetch<SourcesResponse>('admin/sources', { signal }),
    refetchInterval: (query: Query<SourcesResponse>) =>
      query.state.data?.items.some((source) => source.last_run && isActive(source.last_run.status))
        ? POLL_INTERVAL_MS
        : false,
  })
}

/** Các lượt thu thập (mới nhất trước), lọc + phân trang; làm mới 3 giây khi trang đang hiện có lượt chạy. */
export function useRuns(filters: RunFilters) {
  const params = new URLSearchParams({
    page: String(filters.page),
    page_size: String(RUNS_PAGE_SIZE),
  })
  if (filters.site) params.set('site', filters.site)
  if (filters.category) params.set('category', filters.category)
  if (filters.status) params.set('status', filters.status)
  return useQuery({
    queryKey: queryKeys.admin.runs({ ...filters }),
    queryFn: ({ signal }) =>
      apiFetch<ScrapeRunPage>(`admin/scrape-runs?${params.toString()}`, { signal }),
    placeholderData: keepPreviousData,
    refetchInterval: (query: Query<ScrapeRunPage>) =>
      query.state.data?.items.some((run) => isActive(run.status)) ? POLL_INTERVAL_MS : false,
  })
}

/** "Chạy ngay" một nhóm của một trang (202 `{run_id}`); xong thì làm mới nguồn và bảng lượt chạy. */
export function useStartRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ScrapeRunCreate) =>
      apiFetch<ResponseBody<'/api/admin/scrape-runs', 'post', 202>>('admin/scrape-runs', {
        method: 'POST',
        json: body,
      }),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.admin.sources }),
        client.invalidateQueries({ queryKey: queryKeys.admin.runsAll }),
      ]),
  })
}

/** Đề bài challenge của lượt `NEEDS_HUMAN`; 409 `CHALLENGE_NOT_PENDING` nếu không còn chờ. */
export function useChallenge(runId: number | null) {
  return useQuery({
    queryKey: queryKeys.admin.challenge(runId ?? 0),
    queryFn: ({ signal }) =>
      apiFetch<ChallengeView>(`admin/scrape-runs/${runId}/challenge`, { signal }),
    enabled: runId !== null,
    // Mỗi lần mở là một đề bài mới, không dùng lại bản cũ trong bộ nhớ đệm.
    staleTime: 0,
    gcTime: 0,
  })
}

/** Gửi đáp án do người nhập (200 → lượt chạy tiếp ở nền; 400 `CHALLENGE_FAILED` thì thử lại được). */
export function useAnswerChallenge(runId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (answer: string) =>
      apiFetch<ResponseBody<'/api/admin/scrape-runs/{run_id}/challenge', 'post'>>(
        `admin/scrape-runs/${runId}/challenge`,
        {
          method: 'POST',
          json: { answer } satisfies RequestBody<
            '/api/admin/scrape-runs/{run_id}/challenge',
            'post'
          >,
        },
      ),
    onSettled: (_data, error) => {
      // Đáp án sai (400) không đổi gì ở máy chủ nên không cần tải lại; các kết cục khác thì có.
      if (error instanceof ApiError && error.status === 400) return undefined
      return Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.admin.sources }),
        client.invalidateQueries({ queryKey: queryKeys.admin.runsAll }),
      ])
    },
  })
}

/** Hủy lượt đang chờ đáp án (204); 409 `CHALLENGE_NOT_PENDING` nếu lượt không còn chờ. */
export function useCancelChallenge(runId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>(`admin/scrape-runs/${runId}/challenge`, { method: 'DELETE' }),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.admin.sources }),
        client.invalidateQueries({ queryKey: queryKeys.admin.runsAll }),
      ]),
  })
}

/** Làm mới nguồn và bảng lượt chạy (sau khi một lượt đổi trạng thái ở máy chủ). */
export function useRefreshAdmin() {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.admin.sources }),
      client.invalidateQueries({ queryKey: queryKeys.admin.runsAll }),
    ])
}
