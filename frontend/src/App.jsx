import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import { RequireAuth } from './lib/auth.jsx'
import Account from './pages/Account.jsx'
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
        <Route path="devices" element={<Placeholder title="Devices" phase="Phase 1C" />} />
        <Route path="catalog" element={<Placeholder title="Catalog" phase="Phase 1C" />} />
        <Route
          path="configure"
          element={
            <RequireAuth role="engineer">
              <Placeholder title="Configure" phase="Phase 2B" />
            </RequireAuth>
          }
        />
        <Route path="history" element={<Placeholder title="History" phase="Phase 3A" />} />
        <Route path="account" element={<Account />} />
        <Route path="admin/users" element={<RequireAuth role="admin"><Users /></RequireAuth>} />
        <Route path="admin/audit" element={<RequireAuth role="admin"><Audit /></RequireAuth>} />
        <Route path="admin/host-keys" element={<RequireAuth role="admin"><Placeholder title="SSH host keys" phase="Phase 3A" /></RequireAuth>} />
        <Route path="*" element={<Placeholder title="Page not found" phase="no phase – check the address" />} />
      </Route>
    </Routes>
  )
}
