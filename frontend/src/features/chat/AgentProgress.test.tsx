import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { initialAgentRunState, type AgentRunState } from './agentRunReducer'
import { AgentProgress } from './AgentProgress'

const steps = ['Tìm laptop trong danh mục', 'Lọc giá ≤ 30.000.000 ₫', 'So sánh giá giữa các trang']

function state(over: Partial<AgentRunState>): AgentRunState {
  return { ...initialAgentRunState, ...over }
}

describe('AgentProgress', () => {
  it('chưa có kế hoạch: báo đang phân tích yêu cầu', () => {
    render(<AgentProgress state={state({ phase: 'connecting' })} />)
    expect(screen.getByText('Đang phân tích yêu cầu…')).toBeInTheDocument()
  })

  it('có kế hoạch: liệt kê các bước theo thứ tự trong vùng aria-live="polite"', () => {
    render(<AgentProgress state={state({ phase: 'running', steps })} />)
    const items = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(items).toEqual(steps)
    expect(screen.getByRole('region', { name: 'Kế hoạch' })).toBeInTheDocument()
    expect(document.querySelector('[aria-live="polite"]')).not.toBeNull()
    expect(screen.queryByText('Đang phân tích yêu cầu…')).toBeNull()
  })

  it('hiện từng tool với tóm tắt, thời gian và trạng thái cho trình đọc màn hình', () => {
    render(
      <AgentProgress
        state={state({
          phase: 'running',
          steps,
          tools: [
            {
              callId: 'c1',
              tool: 'search_catalog',
              argsSummary: 'laptop',
              status: 'ok',
              summary: 'Tìm thấy 7 sản phẩm',
              durationMs: 84,
            },
            {
              callId: 'c2',
              tool: 'compare_products',
              argsSummary: 'so sánh 2 máy',
              status: 'running',
            },
            {
              callId: 'c3',
              tool: 'get_price_history',
              argsSummary: '',
              status: 'failed',
              summary: 'Không có lịch sử giá',
              durationMs: 5,
            },
          ],
        })}
      />,
    )
    expect(screen.getByText('Xong:')).toBeInTheDocument()
    expect(screen.getByText('Tìm thấy 7 sản phẩm')).toBeInTheDocument()
    expect(screen.getByText('· 84 ms')).toBeInTheDocument()
    expect(screen.getByText('Đang chạy:')).toBeInTheDocument()
    expect(screen.getByText('so sánh 2 máy')).toBeInTheDocument()
    expect(screen.getByText('Lỗi:')).toBeInTheDocument()
    expect(screen.getByText('Không có lịch sử giá')).toBeInTheDocument()
  })

  it('nút Thu gọn/Mở rộng đổi aria-expanded và ẩn nội dung', async () => {
    render(<AgentProgress state={state({ phase: 'running', steps })} />)
    const toggle = screen.getByRole('button', { name: 'Thu gọn' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await userEvent.click(toggle)
    const expand = screen.getByRole('button', { name: 'Mở rộng' })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelector('[aria-live="polite"]')).toHaveClass('hidden')

    await userEvent.click(expand)
    expect(document.querySelector('[aria-live="polite"]')).not.toHaveClass('hidden')
  })

  it('lượt đã xong: không còn bước nào ở trạng thái đang chạy', () => {
    const { container } = render(<AgentProgress state={state({ phase: 'done', steps })} />)
    expect(container.querySelector('.animate-spin')).toBeNull()
  })

  it('đang chạy: đúng một bước đang quay, các bước trước đã xong theo số tool đã chạy xong', () => {
    const { container } = render(
      <AgentProgress
        state={state({
          phase: 'running',
          steps,
          tools: [
            { callId: 'c1', tool: 't', argsSummary: '', status: 'ok', summary: 'x', durationMs: 1 },
          ],
        })}
      />,
    )
    const list = within(screen.getAllByRole('list')[0] as HTMLElement)
    const rows = list.getAllByRole('listitem')
    expect(rows[0]?.querySelector('.text-success')).not.toBeNull()
    expect(rows[1]?.querySelector('.animate-spin')).not.toBeNull()
    expect(rows[2]?.querySelector('.animate-spin')).toBeNull()
    expect(container.querySelectorAll('ol .animate-spin')).toHaveLength(1)
  })

  it('lượt kết thúc mà không có kế hoạch hay tool thì không hiện gì', () => {
    const { container } = render(<AgentProgress state={state({ phase: 'error' })} />)
    expect(container).toBeEmptyDOMElement()
  })
})
