import { useQuery } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { apiFetch } from '@/api/client'
import { server } from '@/mocks/server'
import { apiUrl } from '@/api/client'
import { renderWithProviders } from '@/test/renderWithProviders'
import { QueryBoundary } from './QueryBoundary'
import { EmptyState } from './states'

function Demo() {
  const query = useQuery({
    queryKey: ['demo'],
    queryFn: () => apiFetch<{ items: string[] }>('demo'),
  })
  return (
    <QueryBoundary
      query={query}
      skeleton={<p>khung chờ</p>}
      isEmpty={(data) => data.items.length === 0}
      empty={<EmptyState title="Chưa có gì" description="Hãy thêm một mục" />}
    >
      {(data) => (
        <ul>
          {data.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </QueryBoundary>
  )
}

describe('QueryBoundary', () => {
  it('đang tải: hiện skeleton trong vùng aria-busy', async () => {
    server.use(http.get(apiUrl('demo'), () => HttpResponse.json({ items: ['a'] })))
    renderWithProviders(<Demo />)
    expect(screen.getByText('khung chờ')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(await screen.findByText('a')).toBeInTheDocument()
  })

  it('có dữ liệu: dựng nội dung', async () => {
    server.use(http.get(apiUrl('demo'), () => HttpResponse.json({ items: ['Mock A', 'Mock B'] })))
    renderWithProviders(<Demo />)
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
  })

  it('rỗng: hiện trạng thái rỗng, không hiện danh sách', async () => {
    server.use(http.get(apiUrl('demo'), () => HttpResponse.json({ items: [] })))
    renderWithProviders(<Demo />)
    expect(await screen.findByText('Chưa có gì')).toBeInTheDocument()
    expect(screen.getByText('Hãy thêm một mục')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })

  it('lỗi API: hiện thông điệp tiếng Việt của máy chủ và "Thử lại" gọi lại thành công', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('demo'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { error: { code: 'INTERNAL_ERROR', message: 'Máy chủ đang bận', details: {} } },
              { status: 500 },
            )
          : HttpResponse.json({ items: ['Mock A'] })
      }),
    )
    renderWithProviders(<Demo />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Máy chủ đang bận')

    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('Mock A')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('lỗi mạng: thông điệp mạng mặc định, không lộ chi tiết kỹ thuật', async () => {
    server.use(http.get(apiUrl('demo'), () => HttpResponse.error()))
    renderWithProviders(<Demo />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Không kết nối được máy chủ')
    expect(alert).not.toHaveTextContent(/TypeError|Failed to fetch/)
  })

  it('rỗng mà không truyền `empty` thì dùng tiêu đề rỗng mặc định', async () => {
    server.use(http.get(apiUrl('demo'), () => HttpResponse.json({ items: [] })))
    function Bare() {
      const query = useQuery({
        queryKey: ['bare'],
        queryFn: () => apiFetch<{ items: string[] }>('demo'),
      })
      return (
        <QueryBoundary query={query} skeleton={null} isEmpty={(d) => d.items.length === 0}>
          {() => <p>không tới đây</p>}
        </QueryBoundary>
      )
    }
    renderWithProviders(<Bare />)
    expect(await screen.findByText('Chưa có dữ liệu')).toBeInTheDocument()
  })
})
