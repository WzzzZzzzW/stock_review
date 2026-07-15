import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:  5 * 60 * 1000,   // 5 分钟内不重新请求
      gcTime:     30 * 60 * 1000,  // 30 分钟内缓存不清除（切换 tab 回来立即有数据）
      retry: 1,
      refetchOnWindowFocus: false, // 切回窗口不重新请求
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
