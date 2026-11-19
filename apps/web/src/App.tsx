import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'

import { Shell } from './components/Shell'
import { Analytics } from './pages/Analytics'
import { InvestigationDetail, InvestigationList } from './pages/Investigations'
import { Method } from './pages/Method'
import { Overview } from './pages/Overview'
import { Pipelines } from './pages/Pipelines'
import { Traceability } from './pages/Traceability'
import { Workbench } from './pages/Workbench'

export const routes = [
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'inspect', element: <Workbench /> },
      { path: 'inspect/:imageId', element: <Workbench /> },
      { path: 'analytics', element: <Analytics /> },
      { path: 'trace', element: <Traceability /> },
      { path: 'trace/:unitId', element: <Traceability /> },
      { path: 'investigations', element: <InvestigationList /> },
      { path: 'investigations/:invId', element: <InvestigationDetail /> },
      { path: 'pipelines', element: <Pipelines /> },
      { path: 'pipelines/:runId', element: <Pipelines /> },
      { path: 'method', element: <Method /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })
}

const router = createBrowserRouter(routes)
const queryClient = makeQueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
