import { render, screen } from '@testing-library/react'
import { PriceChange } from './PriceChange'

describe('PriceChange', () => {
  it('rẻ hơn lúc thêm: có mũi tên ↓ và chữ "Giảm …" (không chỉ dùng màu)', () => {
    const { container } = render(
      <PriceChange priceAtAdd={27_990_000} current={27_490_000} delta={-500_000} />,
    )
    expect(screen.getByText('27.990.000 ₫')).toBeInTheDocument()
    expect(screen.getByText('27.490.000 ₫')).toBeInTheDocument()
    const note = screen.getByText('Giảm 500.000 ₫')
    expect(note).toHaveClass('text-success')
    expect(container.querySelector('svg.lucide-arrow-down')).not.toBeNull()
    expect(container.querySelector('svg.lucide-arrow-up')).toBeNull()
  })

  it('đắt hơn lúc thêm: mũi tên ↑ và chữ "Tăng …"', () => {
    const { container } = render(
      <PriceChange priceAtAdd={27_000_000} current={27_500_000} delta={500_000} />,
    )
    expect(screen.getByText('Tăng 500.000 ₫')).toHaveClass('text-warning')
    expect(container.querySelector('svg.lucide-arrow-up')).not.toBeNull()
  })

  it('không đổi giá: "Không đổi", không có mũi tên', () => {
    const { container } = render(
      <PriceChange priceAtAdd={1_000_000} current={1_000_000} delta={0} />,
    )
    expect(screen.getByText('Không đổi')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })

  it('không còn bán: báo "Không còn bán" và không có dòng chênh lệch', () => {
    render(<PriceChange priceAtAdd={1_000_000} current={null} delta={null} />)
    expect(screen.getByText('Không còn bán')).toBeInTheDocument()
    expect(screen.queryByText(/Giảm|Tăng|Không đổi/)).toBeNull()
  })

  it('thiếu giá lúc thêm: hiện dấu gạch, vẫn hiện giá hiện tại', () => {
    render(<PriceChange priceAtAdd={null} current={2_000_000} delta={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getByText('2.000.000 ₫')).toBeInTheDocument()
  })
})
