import { render, screen } from '@testing-library/react'
import { Price, SiteBadge, StaleBadge, ToneBadge } from './badges'

const now = new Date('2026-10-16T12:00:00Z')

describe('StaleBadge', () => {
  it('dữ liệu cũ hơn 24 giờ: hiện "Giá cập nhật lúc HH:mm dd/MM" theo giờ Việt Nam', () => {
    render(<StaleBadge at="2026-10-14T02:00:00Z" now={now} />)
    expect(screen.getByText('Giá cập nhật lúc 09:00 14/10')).toBeInTheDocument()
  })

  it.each([['2026-10-16T11:00:00Z'], [null], [undefined], ['']])(
    'dữ liệu mới hoặc không có mốc (%s): không hiện gì',
    (at) => {
      const { container } = render(<StaleBadge at={at} now={now} />)
      expect(container).toBeEmptyDOMElement()
    },
  )
})

describe('SiteBadge', () => {
  it('hiện tên trang dễ đọc', () => {
    render(<SiteBadge site="fptshop" />)
    expect(screen.getByText('FPT Shop')).toBeInTheDocument()
  })
})

describe('Price', () => {
  it('định dạng VND và dùng chữ số cùng độ rộng', () => {
    render(<Price amount={27490000} />)
    const price = screen.getByText('27.490.000 ₫')
    expect(price).toHaveClass('tabular-nums')
  })
})

describe('ToneBadge', () => {
  it('nghĩa nằm trong chữ chứ không chỉ ở màu', () => {
    render(<ToneBadge tone="danger">BLOCKED</ToneBadge>)
    expect(screen.getByText('BLOCKED')).toBeInTheDocument()
  })
})
