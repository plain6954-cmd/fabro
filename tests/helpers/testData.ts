export const testUser = {
  username: process.env.E2E_USERNAME || 'fabro_e2e_admin',
  password: process.env.E2E_PASSWORD || 'FabroE2E!234',
  email: process.env.E2E_EMAIL || 'fabro.e2e@example.com'
};

export const routes = {
  login: '/login/',
  logout: '/logout/',
  dashboard: '/',
  complaints: '/complaints/',
  addComplaint: '/add-complaint/',
  vehicles: '/car-details/',
  addVehicle: '/add-car-details/',
  sku: '/add-sku/',
  master: '/master-settings/',
  profile: '/profile/',
  adminPanel: '/admin_panel/'
};

export const sample = {
  complaintText: `Playwright complaint ${Date.now()}`,
  vehicleLayout: `PW-${Date.now()}`,
  skuCode: `PW-SKU-${Date.now()}`,
  masterName: `Playwright Master ${Date.now()}`
};
