import { createBrowserRouter, type RouteObject } from 'react-router'
import { AppLayout } from '@/components/layout/AppLayout'
import { AdminPage } from '@/pages/AdminPage'
import { AlertsPage } from '@/pages/AlertsPage'
import { ConversationPage } from '@/pages/ConversationPage'
import { HomePage } from '@/pages/HomePage'
import { ListsPage } from '@/pages/ListsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProductDetailPage } from '@/pages/ProductDetailPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'

/** Bảng route theo docs/08-ui-ux.md §2. Test dùng lại để dựng router bộ nhớ. */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'c/:conversationId', element: <ConversationPage /> },
      { path: 'products/:id', element: <ProductDetailPage /> },
      { path: 'lists', element: <ListsPage /> },
      { path: 'lists/:id', element: <ListsPage /> },
      { path: 'alerts', element: <AlertsPage /> },
      { path: 'admin', element: <AdminPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const createAppRouter = () => createBrowserRouter(routes)
