import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import { RequireAuth } from './lib/auth.jsx'
import Account from './pages/Account.jsx'
import Catalog from './pages/Catalog.jsx'
import Configure from './pages/Configure.jsx'
import Devices from './pages/Devices.jsx'
import History from './pages/History.jsx'
import HostKeys from './pages/admin/HostKeys.jsx'
import Audit from './pages/admin/Audit.jsx'
import Users from './pages/admin/Users.jsx'
import Login from './pages/Login.jsx'
import Placeholder from './pages/Placeholder.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Placeholder title="Overview" phase="Phase 4B" />} />
        <Route path="devices" element={<Devices />} />
        <Route path="catalog" element={<Catalog />} />
        <Route
          path="configure"
          element={
            <RequireAuth role="engineer">
              <Configure />
            </RequireAuth>
          }
        />
        <Route path="history" element={<History />} />
        <Route path="history/:jobId" element={<History />} />
        <Route path="account" element={<Account />} />
        <Route path="admin/users" element={<RequireAuth role="admin"><Users /></RequireAuth>} />
        <Route path="admin/audit" element={<RequireAuth role="admin"><Audit /></RequireAuth>} />
        <Route path="admin/host-keys" element={<RequireAuth role="admin"><HostKeys /></RequireAuth>} />
        <Route path="*" element={<Placeholder title="Page not found" phase="no phase – check the address" />} />
      </Route>
    </Routes>
  )
}
