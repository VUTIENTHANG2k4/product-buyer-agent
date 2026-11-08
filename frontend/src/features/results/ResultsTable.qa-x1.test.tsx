import { screen, within } from '@testing-library/react'
import type { Schemas } from '@/api/types'
import { productRow } from '@/mocks/data'
import { mockMatchMedia, type MatchMediaControl } from '@/test/matchMedia'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ResultsTable } from './ResultsTable'

// QA X1: key_specs của cả 5 nhóm bị JSONB xáo trộn khóa (PostgreSQL xếp theo độ dài khóa).

let media: MatchMediaControl
afterEach(() => media?.restore())

type Category = Schemas['ProductRow']['category']

/** Thứ tự đúng của 4 dòng đầu mỗi nhóm khi đủ dữ liệu (khớp KEY_SPEC_FIELDS ở backend). */
const CASES: {
  category: Category
  specs: Record<string, unknown>
  shown: string[]
}[] = [
  {
    category: 'laptop',
    specs: {
      ram_gb: 16,
      cpu_model: 'i7-13620H',
      storage_gb: 512,
      gpu_model: 'RTX 4060',
      screen_in: 15.6,
      refresh_hz: 144,
    },
    shown: ['CPU: i7-13620H', 'GPU: RTX 4060', 'RAM: 16 GB', 'Ổ cứng: 512 GB'],
  },
  {
    category: 'mouse',
    specs: {
      rgb: true,
      buttons: 6,
      weight_g: 59,
      sensor: 'Hero 2',
      dpi_max: 25600,
      connection: ['wired'],
    },
    shown: ['Kết nối: Có dây', 'DPI tối đa: 25.600 DPI', 'Cảm biến: Hero 2', 'Số nút: 6'],
  },
  {
    category: 'keyboard',
    specs: {
      backlight: 'rgb',
      hot_swap: true,
      form_factor: '75',
      switch_name: 'Red',
      switch_type: 'mechanical',
      connection: ['bluetooth'],
    },
    shown: ['Kết nối: Bluetooth', 'Loại switch: Cơ', 'Switch: Red', 'Kích thước: 75%'],
  },
  {
    category: 'headset',
    specs: { driver_mm: 40, anc: true, has_mic: true, connection: ['usb'], form: 'over_ear' },
    shown: ['Kiểu tai nghe: Chụp tai (over-ear)', 'Kết nối: USB', 'Micro: Có', 'Chống ồn: Có'],
  },
  {
    category: 'phone',
    specs: {
      os: 'Android 16',
      battery_mah: 5000,
      screen_in: 6.7,
      chipset: 'Exynos Mock 1480',
      storage_gb: 128,
      ram_gb: 8,
    },
    shown: ['RAM: 8 GB', 'Ổ cứng: 128 GB', 'Chip xử lý: Exynos Mock 1480', 'Màn hình: 6.7"'],
  },
]

function reversed(specs: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(specs).reverse())
}

function bodyRows() {
  return within(screen.getByRole('table', { name: 'Kết quả tìm kiếm' }))
    .getAllByRole('row')
    .slice(1)
}

function specLines(root: HTMLElement): string[] {
  // Dạng thẻ bọc cả thẻ trong một <li>: chỉ lấy <li> lá (dòng thông số).
  return within(root)
    .queryAllByRole('listitem')
    .filter((item) => item.querySelector('li') === null)
    .map((item) => (item.textContent ?? '').replace(/\s+/g, ' ').trim())
}

describe('ResultsTable · key_specs bị xáo trộn, cả 5 nhóm (QA X1)', () => {
  it.each(CASES)(
    '$category: bảng rộng xếp 4 dòng đầu theo thứ tự nhóm',
    ({ category, specs, shown }) => {
      media = mockMatchMedia(true)
      renderWithProviders(
        <ResultsTable
          rows={[productRow({ product_id: 1, category, key_specs: reversed(specs), offers: [] })]}
        />,
      )
      expect(specLines(bodyRows()[0]!)).toEqual(shown)
    },
  )

  it.each(CASES)(
    '$category: dạng thẻ (dưới 640 px) cũng xếp đúng',
    ({ category, specs, shown }) => {
      media = mockMatchMedia(false)
      const { container } = renderWithProviders(
        <ResultsTable
          rows={[productRow({ product_id: 1, category, key_specs: reversed(specs), offers: [] })]}
        />,
      )
      expect(specLines(container)).toEqual(shown)
    },
  )

  it('iPhone không ghi RAM: bốn dòng đầu là bộ nhớ, chip, màn hình, pin', () => {
    media = mockMatchMedia(true)
    renderWithProviders(
      <ResultsTable
        rows={[
          productRow({
            product_id: 1,
            category: 'phone',
            key_specs: {
              os: 'iOS 18',
              battery_mah: 3561,
              screen_in: 6.1,
              chipset: 'A18',
              storage_gb: 128,
            },
            offers: [],
          }),
        ]}
      />,
    )
    expect(specLines(bodyRows()[0]!)).toEqual([
      'Ổ cứng: 128 GB',
      'Chip xử lý: A18',
      'Màn hình: 6.1"',
      'Pin: 3.561 mAh',
    ])
  })

  it.each([
    ['null', null],
    ['rỗng', {}],
    ['toàn giá trị thiếu', { ram_gb: null, storage_gb: '', chipset: [] }],
  ])('key_specs %s: không dựng danh sách thông số', (_name, specs) => {
    media = mockMatchMedia(true)
    renderWithProviders(
      <ResultsTable
        rows={[
          productRow({
            product_id: 1,
            category: 'phone',
            key_specs: specs as Schemas['ProductRow']['key_specs'],
            offers: [],
          }),
        ]}
      />,
    )
    expect(specLines(bodyRows()[0]!)).toEqual([])
  })

  it('hai nhóm cùng một bảng: mỗi hàng xếp theo nhóm của chính nó', () => {
    media = mockMatchMedia(true)
    const [laptop, phone] = [CASES[0]!, CASES[4]!]
    renderWithProviders(
      <ResultsTable
        rows={[
          productRow({
            product_id: 1,
            category: 'laptop',
            key_specs: reversed(laptop.specs),
            offers: [],
          }),
          productRow({
            product_id: 2,
            category: 'phone',
            key_specs: reversed(phone.specs),
            offers: [],
          }),
        ]}
      />,
    )
    const [first, second] = bodyRows()
    expect(specLines(first!)).toEqual(laptop.shown)
    expect(specLines(second!)).toEqual(phone.shown)
  })

  it('nhóm mới chưa biết ở frontend ("other") giữ thứ tự khóa và không ném lỗi', () => {
    media = mockMatchMedia(true)
    renderWithProviders(
      <ResultsTable
        rows={[
          productRow({
            product_id: 1,
            category: 'other',
            key_specs: { os: 'x', ram_gb: 4 },
            offers: [],
          }),
        ]}
      />,
    )
    expect(specLines(bodyRows()[0]!)).toEqual(['Hệ điều hành: x', 'RAM: 4 GB'])
  })

  it('chipset có HTML hiện như văn bản, không dựng phần tử', () => {
    media = mockMatchMedia(true)
    const html = '<img src=x onerror=alert(1)>'
    const { container } = renderWithProviders(
      <ResultsTable
        rows={[
          productRow({
            product_id: 1,
            category: 'phone',
            key_specs: { chipset: html },
            offers: [],
          }),
        ]}
      />,
    )
    expect(container.querySelector('img[src="x"]')).toBeNull()
    expect(specLines(bodyRows()[0]!)).toEqual([`Chip xử lý: ${html}`])
  })

  it('danh sách 300 điện thoại hiện đủ 300 hàng và mỗi hàng đúng 4 dòng thông số', () => {
    media = mockMatchMedia(true)
    const phone = CASES[4]!
    const rows = Array.from({ length: 300 }, (_unused, index) =>
      productRow({
        product_id: index + 1,
        name: `Điện thoại Mock ${index + 1}`,
        category: 'phone',
        key_specs: reversed(phone.specs),
        offers: [],
      }),
    )
    renderWithProviders(<ResultsTable rows={rows} />)
    const body = bodyRows()
    expect(body).toHaveLength(300)
    expect(specLines(body[299]!)).toEqual(phone.shown)
  })
})
