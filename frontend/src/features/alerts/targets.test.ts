import { parseTargetPrice, suggestTargets } from './targets'

describe('suggestTargets', () => {
  it('gợi ý −5% và −10%, làm tròn tới 1.000 ₫', () => {
    expect(suggestTargets(27_490_000)).toEqual([
      { percent: 5, price: 26_116_000 },
      { percent: 10, price: 24_741_000 },
    ])
    expect(suggestTargets(10_000_000)).toEqual([
      { percent: 5, price: 9_500_000 },
      { percent: 10, price: 9_000_000 },
    ])
  })

  it('luôn thấp hơn giá hiện tại và là số nguyên dương, kể cả giá rất nhỏ', () => {
    for (const price of [2, 100, 999, 1_001, 1_500, 5_000_000_000]) {
      for (const suggestion of suggestTargets(price)) {
        expect(Number.isInteger(suggestion.price)).toBe(true)
        expect(suggestion.price).toBeGreaterThanOrEqual(1)
        expect(suggestion.price).toBeLessThan(price)
      }
    }
  })

  it('giá 1 ₫ thì không có gợi ý hợp lệ', () => {
    expect(suggestTargets(1)).toEqual([])
  })
})

describe('parseTargetPrice', () => {
  it.each([
    ['25000000', 25_000_000],
    ['25.000.000', 25_000_000],
    ['25,000,000', 25_000_000],
    [' 25 000 000 ', 25_000_000],
    ['25.000.000 ₫', 25_000_000],
    ['25000000đ', 25_000_000],
    ['25000000 VND', 25_000_000],
    ['1', 1],
  ])('%j → %d', (input, expected) => {
    expect(parseTargetPrice(input)).toBe(expected)
  })

  it.each([
    '',
    '   ',
    '0',
    '-5',
    '27.5',
    '27,5',
    '1.2345.000',
    'abc',
    '25 triệu',
    '1e6',
    '99999999999999',
  ])('từ chối %j', (input) => {
    expect(parseTargetPrice(input)).toBeNull()
  })
})
