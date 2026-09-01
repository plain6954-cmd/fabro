from locust import HttpUser, task, between

class FabroUser(HttpUser):
    # Simulate realistic delay between requests (1 to 3 seconds)
    wait_time = between(1, 3)

    @task(3)
    def view_login_page(self):
        """Simulate a user visiting the login page."""
        self.client.get("/login/")

    @task(1)
    def view_logout_success(self):
        """Simulate a user visiting the logout success page."""
        self.client.get("/logout-success/")

    @task(2)
    def view_dashboard_redirect(self):
        """Simulate an unauthenticated user hitting the dashboard root, which triggers a redirect."""
        self.client.get("/", allow_redirects=True)
