import { http, HttpResponse } from 'msw'
import { apiUrl } from '@/api/client'
import type { Schemas } from '@/api/types'
import { healthView, scrapeRunView } from '@/mocks/data'
import { server } from '@/mocks/server'

type Run = Schemas['ScrapeRunView']
type Source = Schemas['SourceView']

export interface ApiFailure {
  status: number
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface FakeAdmin {
  health: Schemas['HealthResponse']
  sources: Source[]
  /** Mọi lượt, mới nhất trước; test sửa trực tiếp được để giả lập tiến triển ở máy chủ. */
  runs: Run[]
  /** Địa chỉ GET đã nhận (gồm query): `"admin/scrape-runs?page=1&page_size=10"`. */
  reads: string[]
  /** Yêu cầu ghi đã nhận: `'POST admin/scrape-runs {"site":...}'`. */
  writes: string[]
  /** Gán thì `POST /admin/scrape-runs` trả lỗi này; mặc định 202 và thêm một lượt RUNNING. */
  startFailure: ApiFailure | null
  /** Đề bài của `GET .../challenge`; một `ApiFailure` thì trả lỗi đó. */
  challenge: Schemas['ChallengeView'] | ApiFailure
  /** Quyết định kết quả của `POST .../challenge` theo đáp án. */
  answer: (answer: string) => ApiFailure | null
  /** Gán thì `DELETE .../challenge` trả lỗi này; mặc định 204 và lượt chuyển sang FAILED. */
  cancelFailure: ApiFailure | null
}

const failure = (f: ApiFailure) =>
  HttpResponse.json(
    { error: { code: f.code, message: f.message, details: f.details ?? {} } },
    { status: f.status },
  )

const isFailure = (value: unknown): value is ApiFailure =>
  typeof value === 'object' && value !== null && 'status' in value

/** Máy chủ quản trị thu thập giả (health, nguồn, lượt chạy có lọc + phân trang, challenge) bằng MSW. */
export function installFakeAdmin(initial: Partial<Pick<FakeAdmin, 'sources' | 'runs'>> = {}) {
  const fake: FakeAdmin = {
    health: healthView(),
    sources: structuredClone(initial.sources ?? []),
    runs: structuredClone(initial.runs ?? []),
    reads: [],
    writes: [],
    startFailure: null,
    challenge: { kind: 'captcha', prompt: 'AB12C', image_url: null },
    answer: () => null,
    cancelFailure: null,
  }
  let nextRunId = Math.max(0, ...fake.runs.map((run) => run.run_id)) + 1

  server.use(
    http.get(apiUrl('health'), () => HttpResponse.json(fake.health)),
    http.get(apiUrl('admin/sources'), ({ request }) => {
      fake.reads.push(`admin/sources${new URL(request.url).search}`)
      return HttpResponse.json({ items: fake.sources })
    }),
    http.get(apiUrl('admin/scrape-runs'), ({ request }) => {
      const url = new URL(request.url)
      fake.reads.push(`admin/scrape-runs${url.search}`)
      const params = url.searchParams
      const matching = fake.runs.filter(
        (run) =>
          (params.get('site') ?? run.site) === run.site &&
          (params.get('category') ?? run.category) === run.category &&
          (params.get('status') ?? run.status) === run.status,
      )
      const page = Number(params.get('page') ?? 1)
      const pageSize = Number(params.get('page_size') ?? 20)
      return HttpResponse.json({
        items: matching.slice((page - 1) * pageSize, page * pageSize),
        total: matching.length,
        page,
        page_size: pageSize,
      })
    }),
    http.post(apiUrl('admin/scrape-runs'), async ({ request }) => {
      const text = await request.text()
      fake.writes.push(`POST admin/scrape-runs ${text}`)
      if (fake.startFailure) return failure(fake.startFailure)
      const body = JSON.parse(text) as Pick<Run, 'site' | 'category'>
      const run = scrapeRunView({
        run_id: nextRunId++,
        site: body.site,
        category: body.category,
        status: 'RUNNING',
        pages_fetched: 0,
        items_parsed: 0,
        items_failed: 0,
        offers_upserted: 0,
        price_changes: 0,
        finished_at: null,
      })
      fake.runs.unshift(run)
      return HttpResponse.json({ run_id: run.run_id }, { status: 202 })
    }),
    http.get(apiUrl('admin/scrape-runs/:id/challenge'), ({ params }) => {
      fake.reads.push(`admin/scrape-runs/${String(params.id)}/challenge`)
      return isFailure(fake.challenge) ? failure(fake.challenge) : HttpResponse.json(fake.challenge)
    }),
    http.post(apiUrl('admin/scrape-runs/:id/challenge'), async ({ params, request }) => {
      const text = await request.text()
      fake.writes.push(`POST admin/scrape-runs/${String(params.id)}/challenge ${text}`)
      const outcome = fake.answer((JSON.parse(text) as { answer: string }).answer)
      if (outcome) return failure(outcome)
      const run = fake.runs.find((candidate) => candidate.run_id === Number(params.id))
      if (run) Object.assign(run, { status: 'RUNNING', challenge_kind: null })
      return HttpResponse.json({ status: 'RUNNING' })
    }),
    http.delete(apiUrl('admin/scrape-runs/:id/challenge'), ({ params }) => {
      fake.writes.push(`DELETE admin/scrape-runs/${String(params.id)}/challenge`)
      if (fake.cancelFailure) return failure(fake.cancelFailure)
      const run = fake.runs.find((candidate) => candidate.run_id === Number(params.id))
      if (run) Object.assign(run, { status: 'FAILED', challenge_kind: null })
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return fake
}
