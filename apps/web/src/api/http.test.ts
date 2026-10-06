import { describe, expect, it } from "vitest";
import { refusal } from "./http";

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("refusal", () => {
  it("carries the API's own sentence", async () => {
    const refused = await refusal(answer(409, { detail: "USD Coin already holds this." }), "No.");

    expect(refused.status).toBe(409);
    expect(refused.message).toBe("USD Coin already holds this.");
  });

  it("reads a validation refusal's own sentences", async () => {
    const refused = await refusal(
      answer(422, {
        detail: [
          {
            type: "value_error",
            loc: ["body", "token", "pegged_currency"],
            msg: "Value error, A currency code is three letters, like USD.",
          },
          {
            type: "value_error",
            loc: ["body", "token", "name"],
            msg: "Value error, A name cannot be blank.",
          },
        ],
      }),
      "The Instrument could not be added.",
    );

    expect(refused.message).toBe(
      "A currency code is three letters, like USD. A name cannot be blank.",
    );
  });

  it("names the field where the validator's sentence does not", async () => {
    const refused = await refusal(
      answer(422, {
        detail: [
          { type: "missing", loc: ["body", "token", "contract_address"], msg: "Field required" },
        ],
      }),
      "The Instrument could not be added.",
    );

    expect(refused.message).toBe("contract_address: Field required.");
  });

  it("falls back, with what to do, where there is no sentence to read", async () => {
    for (const body of [{ detail: [] }, { detail: [{ unexpected: true }] }, {}]) {
      const refused = await refusal(answer(422, body), "The Instrument could not be added.");

      expect(refused.message).toMatch(/^The Instrument could not be added\. The API answered 422/);
    }
  });
});
