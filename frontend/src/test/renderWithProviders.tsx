import { QueryClient } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { Providers } from '@/app/providers'

/** QueryClient cho test: không thử lại, không giữ cache giữa các test. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
}

interface Options {
  /** Đường dẫn ban đầu của `MemoryRouter`. */
  route?: string
  client?: QueryClient
}

/** Dựng component trong QueryClient + MemoryRouter; trả thêm `client` để kiểm cache. */
export function renderWithProviders(
  ui: ReactElement,
  { route = '/', client = createTestQueryClient() }: Options = {},
): RenderResult & { client: QueryClient } {
  const view = render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </Providers>,
  )
  return { ...view, client }
}
