/** Dữ liệu gắn vào `handle` của route (docs/08 §2): tiêu đề dùng cho `document.title`. */
export interface RouteHandle {
  title: string
}

function isRouteHandle(value: unknown): value is RouteHandle {
  return (
    typeof value === 'object' &&
    value !== null &&
    'title' in value &&
    typeof (value as { title: unknown }).title === 'string'
  )
}

/** Lấy tiêu đề của route khớp sâu nhất có khai báo `handle.title`. */
export function titleFromMatches(matches: readonly { handle: unknown }[]): string | undefined {
  const match = matches.findLast((m) => isRouteHandle(m.handle))
  return match && isRouteHandle(match.handle) ? match.handle.title : undefined
}
