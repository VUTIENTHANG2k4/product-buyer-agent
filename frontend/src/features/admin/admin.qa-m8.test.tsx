import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { apiUrl } from '@/api/client'
import { scrapeRunView, sourceView } from '@/mocks/data'
import { server } from '@/mocks/server'
import { installFakeAdmin } from '@/test/fakeAdmin'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { isValidAnswer } from './answer'
import { ChallengeDialog } from './ChallengeDialog'
import { RunsSection } from './RunsSection'

const NBSP = String.fromCharCode(0xa0)
const EM_SPACE = String.fromCharCode(0x2003)
const IDEOGRAPHIC = String.fromCharCode(0x3000)
const ZWSP = String.fromCharCode(0x200b)
const LINE_SEP = String.fromCharCode(0x2028)

describe('isValidAnswer · ký tự đặc biệt (QA M8)', () => {
  const nul = String.fromCharCode(0)

  it.each([
    ['AB 12 C', 'khoảng trắng giữa'],
    ['\u{1F600}', 'emoji'],
    ['\u0007', 'ký tự điều khiển BEL (máy chủ chỉ cấm NUL)'],
    [ZWSP, 'zero-width space đơn lẻ (không bị trim)'],
    ['Đ̣', 'dấu tiếng Việt tổ hợp'],
    ['a'.repeat(200), 'đúng 200 ký tự'],
  ])('hợp lệ: %j (%s)', (answer) => {
    expect(isValidAnswer(answer)).toBe(true)
  })

  it.each([
    [NBSP + EM_SPACE + IDEOGRAPHIC, 'toàn khoảng trắng Unicode (NBSP, em space, ideographic)'],
    ['a'.repeat(201), '201 ký tự'],
    [nul, 'chỉ NUL'],
    [`${'a'.repeat(100)}${nul}`, 'NUL ở cuối'],
    [LINE_SEP, 'dấu ngắt dòng U+2028'],
  ])('không hợp lệ: %j (%s)', (answer) => {
    expect(isValidAnswer(answer)).toBe(false)
  })

  it('khoảng trắng Unicode hai đầu được cắt trước khi đếm độ dài', () => {
    expect(isValidAnswer(`${NBSP}${'a'.repeat(200)}${IDEOGRAPHIC}`)).toBe(true)
  })

  // BUG-M8-7 (cùng nhóm với ghi chú danh sách): độ dài đếm theo đơn vị UTF-16, máy chủ (Pydantic) đếm
  // theo điểm mã. 150 emoji là 150 ký tự với máy chủ (≤ 200) nhưng 300 đơn vị nên giao diện từ chối.
  // Rất thấp (đáp án captcha là chuỗi ngắn). XPASS báo đỏ: gỡ `.fails` khi sửa.
  it('150 emoji (150 điểm mã) nằm trong giới hạn 200 ký tự', () => {
    expect(isValidAnswer('\u{1F600}'.repeat(150))).toBe(true)
  })
})

let media: MatchMediaControl
beforeEach(() => {
  media = mockMatchMedia(true)
})
afterEach(() => media.restore())

const runs = (count: number) =>
  Array.from({ length: count }, (_, index) =>
    scrapeRunView({ run_id: count - index, started_at: '2026-10-16T02:00:00Z' }),
  )

const dataRows = () =>
  within(screen.getByRole('table', { name: 'Danh sách lượt thu thập' }))
    .getAllByRole('row')
    .slice(1)

describe('RunsSection · phân trang biên (QA M8)', () => {
  it('25 lượt = 3 trang: trang cuối có 5 hàng, nút Sau tắt, Trước bật', async () => {
    const fake = installFakeAdmin({ runs: runs(25) })
    renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    expect(await screen.findByText('Trang 1 / 3')).toBeInTheDocument()
    expect(screen.getByText('25 lượt')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('Trang 3 / 3')).toBeInTheDocument()
    await waitFor(() => expect(dataRows()).toHaveLength(5))
    expect(screen.getByRole('button', { name: 'Trang sau' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Trang trước' })).toBeEnabled()
    expect(fake.reads.some((read) => read.includes('page=3&page_size=10'))).toBe(true)
  })

  it('đúng 10 lượt = 1 trang (không có trang 2 trống); 11 lượt = 2 trang', async () => {
    installFakeAdmin({ runs: runs(10) })
    const first = renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    expect(await screen.findByText('Trang 1 / 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trang sau' })).toBeDisabled()
    first.unmount()

    installFakeAdmin({ runs: runs(11) })
    renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    expect(await screen.findByText('Trang 1 / 2')).toBeInTheDocument()
  })

  it('dữ liệu co lại khi đang ở trang 3 (total 3, items rỗng): hiện "Trang 3 / 1" và Trước đưa về được dữ liệu', async () => {
    const fake = installFakeAdmin({ runs: runs(25) })
    const { client } = renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    await screen.findByText('Trang 1 / 3')
    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Trang sau' }))
    await screen.findByText('Trang 3 / 3')

    fake.runs.length = 3
    await client.invalidateQueries({ queryKey: ['admin', 'runs'] })
    expect(await screen.findByText('Trang 3 / 1')).toBeInTheDocument()
    expect(screen.getByText('3 lượt')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trang sau' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Trang trước' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Trang trước' }))
    expect(await screen.findByText('Trang 1 / 1')).toBeInTheDocument()
    await waitFor(() => expect(dataRows()).toHaveLength(3))
  })

  it('máy chủ trả total 0 ở trang 2: không ném lỗi, hiện "Trang 2 / 1"', async () => {
    let page = 1
    server.use(
      http.get(apiUrl('admin/scrape-runs'), ({ request }) => {
        page = Number(new URL(request.url).searchParams.get('page'))
        return HttpResponse.json(
          page === 1
            ? { items: runs(10), total: 25, page, page_size: 10 }
            : { items: [], total: 0, page, page_size: 10 },
        )
      }),
    )
    renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    await screen.findByText('Trang 1 / 3')
    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('Trang 2 / 1')).toBeInTheDocument()
    expect(screen.getByText('0 lượt')).toBeInTheDocument()
  })

  it('mã lượt rất lớn (2^53 − 1) hiện đủ chữ số và truyền đúng cho nút Xử lý', async () => {
    const huge = Number.MAX_SAFE_INTEGER
    installFakeAdmin({
      runs: [scrapeRunView({ run_id: huge, status: 'NEEDS_HUMAN', challenge_kind: 'captcha' })],
    })
    const onHandle = vi.fn()
    renderWithProviders(<RunsSection sources={[]} onHandle={onHandle} />)
    expect(await screen.findByRole('cell', { name: `#${huge}` })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: `Xử lý challenge của lượt #${huge}` }))
    expect(onHandle).toHaveBeenCalledWith(huge)
  })

  it('lượt BLOCKED cũ hơn lượt mới nhất của nguồn không hiện giờ thử lại; lượt mới nhất hiện', async () => {
    const blockedOld = scrapeRunView({ run_id: 3, status: 'BLOCKED', error_message: 'cũ' })
    const blockedNew = scrapeRunView({ run_id: 4, status: 'BLOCKED', error_message: 'mới' })
    installFakeAdmin({ runs: [blockedNew, blockedOld] })
    const source = sourceView({
      key: 'mockshop',
      last_run: blockedNew,
      cooldown_until: '2099-01-01T05:00:00Z',
    })
    renderWithProviders(<RunsSection sources={[source]} onHandle={vi.fn()} />)
    await screen.findByRole('cell', { name: '#4' })
    const retryTexts = screen.getAllByText(/Thử lại được sau/)
    expect(retryTexts).toHaveLength(1)
    expect(retryTexts[0]).toHaveTextContent('12:00 01/01/2099')
  })

  it('lý do lỗi dài 5.000 ký tự và chứa HTML hiện như văn bản, không dựng phần tử', async () => {
    const reason = `<b>x</b> ${'rất dài '.repeat(700)}`
    installFakeAdmin({
      runs: [scrapeRunView({ run_id: 1, status: 'FAILED', error_message: reason })],
    })
    const { container } = renderWithProviders(<RunsSection sources={[]} onHandle={vi.fn()} />)
    await screen.findByRole('cell', { name: '#1' })
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByText(/^Lý do: <b>x<\/b>/)).toBeInTheDocument()
  })
})

describe('ChallengeDialog · đáp án biên (QA M8)', () => {
  async function openDialog(runId = 9) {
    const onResolved = vi.fn()
    const view = renderWithProviders(
      <ChallengeDialog runId={runId} onOpenChange={vi.fn()} onResolved={onResolved} />,
    )
    const input = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Đáp án' })
    return { ...view, onResolved, input }
  }

  const submit = () => userEvent.click(screen.getByRole('button', { name: 'Gửi đáp án' }))

  it('đáp án đúng 200 ký tự được gửi đủ 200', async () => {
    const fake = installFakeAdmin()
    const { input } = await openDialog()
    fireEvent.change(input, { target: { value: 'x'.repeat(200) } })
    await submit()
    await waitFor(() => expect(fake.writes).toHaveLength(1))
    const body = JSON.parse(fake.writes[0]!.replace(/^POST \S+ /, '')) as { answer: string }
    expect(body.answer).toHaveLength(200)
  })

  it('đáp án 201 ký tự bị chặn ở bước gửi với thông báo 1–200 ký tự, không gọi API', async () => {
    const fake = installFakeAdmin()
    const { input } = await openDialog()
    fireEvent.change(input, { target: { value: 'x'.repeat(201) } })
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Hãy nhập đáp án (1–200 ký tự).')
    expect(fake.writes).toEqual([])
  })

  it('khoảng trắng Unicode hai đầu bị cắt, khoảng trắng giữa giữ nguyên', async () => {
    const fake = installFakeAdmin()
    const { input } = await openDialog()
    fireEvent.change(input, { target: { value: `${NBSP}${IDEOGRAPHIC}AB 12 C${NBSP}` } })
    await submit()
    await waitFor(() => expect(fake.writes).toHaveLength(1))
    expect(fake.writes[0]).toBe('POST admin/scrape-runs/9/challenge {"answer":"AB 12 C"}')
  })

  it('đáp án chứa emoji và dấu tiếng Việt tổ hợp được gửi nguyên vẹn (JSON UTF-8)', async () => {
    const fake = installFakeAdmin()
    const { input } = await openDialog()
    const answer = `Đà Nẵng ${'\u{1F600}'} ${'ệ'}`
    fireEvent.change(input, { target: { value: answer } })
    await submit()
    await waitFor(() => expect(fake.writes).toHaveLength(1))
    const body = JSON.parse(fake.writes[0]!.replace(/^POST \S+ /, '')) as { answer: string }
    expect(body.answer).toBe(answer)
  })

  it('đáp án chứa NUL (dán vào): báo sai tại chỗ, không gọi API', async () => {
    const fake = installFakeAdmin()
    const { input } = await openDialog()
    fireEvent.change(input, { target: { value: `AB${String.fromCharCode(0)}C` } })
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Hãy nhập đáp án (1–200 ký tự).')
    expect(fake.writes).toEqual([])
  })

  it('bấm Gửi hai lần liên tiếp khi đang chờ máy chủ chỉ gửi một yêu cầu', async () => {
    installFakeAdmin()
    let posts = 0
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(apiUrl('admin/scrape-runs/:id/challenge'), async () => {
        posts += 1
        await gate
        return HttpResponse.json({ status: 'RUNNING' })
      }),
    )
    const { input, onResolved } = await openDialog()
    await userEvent.type(input, 'AB12C')
    await submit()
    await screen.findByRole('button', { name: 'Đang gửi…' })
    await userEvent.type(input, '{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Đang gửi…' }))
    release()
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith('answered'))
    expect(posts).toBe(1)
  })

  it('sai đáp án rồi đổi sang lượt khác: ô nhập và thông báo lỗi của lượt cũ không còn', async () => {
    const fake = installFakeAdmin()
    fake.answer = () => ({ status: 400, code: 'CHALLENGE_FAILED', message: 'Đáp án không đúng.' })
    function Harness() {
      const [runId, setRunId] = useState(9)
      return (
        <>
          <ChallengeDialog runId={runId} onOpenChange={vi.fn()} onResolved={vi.fn()} />
          <button type="button" onClick={() => setRunId(10)}>
            sang lượt 10
          </button>
        </>
      )
    }
    renderWithProviders(<Harness />)
    const input = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Đáp án' })
    await userEvent.type(input, 'sai')
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Đáp án không đúng.')

    // Hộp thoại là modal nên nút nền bị ẩn khỏi cây trợ năng: bấm thẳng bằng fireEvent.
    fireEvent.click(screen.getByText('sang lượt 10'))
    await waitFor(() =>
      expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Đáp án' })).toHaveValue(''),
    )
    expect(screen.queryByRole('alert')).toBeNull()
    expect(fake.reads).toContain('admin/scrape-runs/10/challenge')
  })
})
