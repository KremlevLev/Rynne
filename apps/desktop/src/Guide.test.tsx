import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Guide } from "./Guide";

describe("Guide", () => {
  it("provides detailed Russian and English handbooks", () => {
    const view = render(<Guide locale="ru" />);
    expect(screen.getByText("Ставьте цель обычными словами")).toBeInTheDocument();
    expect(screen.getByText("Научите Rynne вашему workflow")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(8);

    view.rerender(<Guide locale="en" />);
    expect(screen.getByText("Describe the outcome in plain language")).toBeInTheDocument();
    expect(screen.getByText("Teach Rynne your workflow")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(8);
  });
});
