import { createBrowserRouter, type RouteObject } from 'react-router'
import { AppLayout } from '@/components/layout/AppLayout'
import type { RouteHandle } from '@/lib/routeTitle'
import { strings } from '@/lib/strings'
import { AdminPage } from '@/pages/AdminPage'
import { AlertsPage } from '@/pages/AlertsPage'
import { ConversationPage } from '@/pages/ConversationPage'
import { HomePage } from '@/pages/HomePage'
import { ListsPage } from '@/pages/ListsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProductDetailPage } from '@/pages/ProductDetailPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'

const title = (value: string): RouteHandle => ({ title: value })

/** Bảng route theo docs/08-ui-ux.md §2. Test dùng lại để dựng router bộ nhớ. */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <HomePage />, handle: title(strings.nav.home) },
      {
        path: 'c/:conversationId',
        element: <ConversationPage />,
        handle: title(strings.pages.conversation.title),
      },
      {
        path: 'products/:id',
        element: <ProductDetailPage />,
        handle: title(strings.pages.product.title),
      },
      { path: 'lists', element: <ListsPage />, handle: title(strings.pages.lists.title) },
      { path: 'lists/:id', element: <ListsPage />, handle: title(strings.pages.list.title) },
      { path: 'alerts', element: <AlertsPage />, handle: title(strings.pages.alerts.title) },
      { path: 'admin', element: <AdminPage />, handle: title(strings.pages.admin.title) },
      { path: '*', element: <NotFoundPage />, handle: title(strings.pages.notFound.title) },
    ],
  },
]

export const createAppRouter = () => createBrowserRouter(routes)
