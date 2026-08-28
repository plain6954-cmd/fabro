export const testUser = {
  username: process.env.E2E_USERNAME || 'fabro_e2e_admin',
  password: process.env.E2E_PASSWORD || 'FabroE2E!234',
  email: process.env.E2E_EMAIL || 'fabro.e2e@example.com'
};

export const workflowUsers = {
  factory: { username: 'fabro_e2e_factory', password: 'FabroWorkflow!234' },
  pm: { username: 'fabro_e2e_pm', password: 'FabroWorkflow!234' },
  om: { username: 'fabro_e2e_om', password: 'FabroWorkflow!234' },
  cad: { username: 'fabro_e2e_cad', password: 'FabroWorkflow!234' },
  ed: { username: 'fabro_e2e_ed', password: 'FabroWorkflow!234' }
};

export const routes = {
  login: '/login/',
  logout: '/logout/',
  dashboard: '/',
  complaints: '/complaints/',
  addComplaint: '/add-complaint/',
  vehicles: '/car-details/',
  addVehicle: '/car-details/',
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
