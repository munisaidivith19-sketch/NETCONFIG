import { configure } from '@testing-library/react'

// findBy*/waitFor wait 1 s by default. With every test file running in parallel (and the backend tests on the
// same PC) the larger pages can take longer to render, so allow 5 s before a query fails.
configure({ asyncUtilTimeout: 5000 })
