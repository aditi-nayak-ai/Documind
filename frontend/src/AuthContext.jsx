import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../AuthContext";
import AuthPage from "./AuthPage";
 
// AuthPage/AuthContext talk to the backend through this module's `api`
// instance. Mocking it here means the test exercises the REAL component
// tree and REAL state transitions (tab switching, the info message,
// whether localStorage gets written to) without needing a live backend --
// the previous test suite only used renderToStaticMarkup, which can't
// simulate a click or a form submit at all, so it could never have
// caught this bug.
vi.mock("../api", () => ({
  api: { post: vi.fn(), get: vi.fn() },
  setUnauthorizedHandler: vi.fn(),
}));
import { api } from "../api";
 
const TOKEN_KEY = "documind_token";
 
function renderAuthPage() {
  return render(
    <AuthProvider>
      <AuthPage />
    </AuthProvider>
  );
}
 
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});
 
describe("signup no longer logs the user in", () => {
  it("does not store a token after a successful registration", async () => {
    api.post.mockResolvedValueOnce({ data: { access_token: "token-that-must-not-be-used" } });
    const user = userEvent.setup();
    renderAuthPage();
 
    await user.click(screen.getByText("Sign up"));
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
 
    expect(api.post).toHaveBeenCalledWith("/auth/register", {
      email: "new@example.com",
      password: "a-real-password-1",
    });
    // The core regression this test guards: registering used to store
    // whatever access_token the backend returned and flip the app
    // straight to the upload screen. It must not do that anymore.
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
 
  it("switches to the login tab and prompts the user to log in", async () => {
    api.post.mockResolvedValueOnce({ data: { access_token: "unused" } });
    const user = userEvent.setup();
    renderAuthPage();
 
    await user.click(screen.getByText("Sign up"));
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
 
    expect(await screen.findByText("Account created. Log in to continue.")).toBeInTheDocument();
    // The submit button's label is mode-driven -- "Log in" only renders
    // once mode has actually flipped from "register" back to "login".
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();
  });
 
  it("clears the password field after registering, but keeps the email", async () => {
    api.post.mockResolvedValueOnce({ data: { access_token: "unused" } });
    const user = userEvent.setup();
    renderAuthPage();
 
    await user.click(screen.getByText("Sign up"));
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
 
    await screen.findByText("Account created. Log in to continue.");
    expect(screen.getByLabelText("Email")).toHaveValue("new@example.com");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
 
  it("still lets the user actually log in afterward, and that DOES store a token", async () => {
    api.post
      .mockResolvedValueOnce({ data: { access_token: "unused" } }) // register
      .mockResolvedValueOnce({ data: { access_token: "real-session-token" } }); // login
    const user = userEvent.setup();
    renderAuthPage();
 
    await user.click(screen.getByText("Sign up"));
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByText("Account created. Log in to continue.");
 
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: "Log in" }));
 
    expect(api.post).toHaveBeenLastCalledWith("/auth/login", {
      email: "new@example.com",
      password: "a-real-password-1",
    });
    await vi.waitFor(() => expect(localStorage.getItem(TOKEN_KEY)).toBe("real-session-token"));
  });
 
  it("clears the info message when the user manually switches tabs", async () => {
    api.post.mockResolvedValueOnce({ data: { access_token: "unused" } });
    const user = userEvent.setup();
    renderAuthPage();
 
    await user.click(screen.getByText("Sign up"));
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a-real-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByText("Account created. Log in to continue.");
 
    await user.click(screen.getByText("Sign up"));
    expect(screen.queryByText("Account created. Log in to continue.")).not.toBeInTheDocument();
  });
});
