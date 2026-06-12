import { test, expect } from '../fixtures';
import { LoginPage } from '../pages/login.page';
import { HomePage } from '../pages/home.page';

// Access-control journeys at the boundary a real user would hit through the
// browser. These map directly to the risk register:
//   - R-004 (authorization bypass): a logged-in member must not reach admin.
//   - Authentication enforcement: an anonymous visitor must be sent to login.
// Counterpart to functional/test_access_control.py.
test.describe('Access control', () => {
  test('member cannot reach the admin area (R-004)', async ({ memberPage: page }) => {
    await page.goto('/admin/dashboard');

    // admin_required redirects non-admins home with a flash, rather than
    // rendering the admin page. Assert the path is root (host-agnostic).
    expect(new URL(page.url()).pathname).toBe('/');
    await expect(new HomePage(page).alert).toContainText('Access denied');
  });

  test('anonymous visitor is sent to login', async ({ page }) => {
    await page.goto('/member/dashboard');

    await expect(page).toHaveURL(/\/auth\/login/);
    await expect(new LoginPage(page).form).toBeVisible();
  });
});
