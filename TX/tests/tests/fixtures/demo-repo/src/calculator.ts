import { add, multiply, divide } from "./math";

export class Calculator {
  private history: number[] = [];

  add(a: number, b: number): number {
    const result = add(a, b);
    this.history.push(result);
    return result;
  }

  multiply(a: number, b: number): number {
    const result = multiply(a, b);
    this.history.push(result);
    return result;
  }

  divide(a: number, b: number): number {
    const result = divide(a, b);
    this.history.push(result);
    return result;
  }

  getHistory(): number[] {
    return [...this.history];
  }
}
