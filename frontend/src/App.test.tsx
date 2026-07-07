import { render, screen } from "@testing-library/react"
import { ProjectsPage } from "./pages/ProjectsPage"

test("projects page renders heading", () => {
  render(<ProjectsPage />)
  expect(screen.getByText("Projects")).toBeDefined()
})
