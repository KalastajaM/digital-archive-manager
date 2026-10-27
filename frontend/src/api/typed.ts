/** Types for calling the API by its OpenAPI paths (made by ``npm run gen:api``): a
 * path's parameters, its query, its JSON body and its 200 answer. The calls themselves
 * are ``apiGet``, ``apiPost`` and ``apiDelete`` in ``client.ts``, over its ``request()``
 * (same headers, AbortSignal and NetworkError). ``buildUrl`` fills a path template like
 * ``/api/maintenance/jobs/{job_id}`` and appends the query.
 *
 * The answer comes from ``schema.d.ts``, where a field with a default is always there
 * (the server always sends it). What is sent comes from ``schema-input.d.ts``, the same
 * schema with such fields optional, because the page may leave them to the server. */
import type { paths } from "./schema";
import type { paths as inputPaths } from "./schema-input";

export type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

/** The paths that answer ``M``. */
export type PathOf<M extends HttpMethod> = {
  [P in keyof paths]: [NonNullable<paths[P][M]>] extends [never] ? never : P;
}[keyof paths];

/** The OpenAPI operation of ``M`` on ``P`` (its answers). */
export type Operation<P extends keyof paths, M extends HttpMethod> = NonNullable<paths[P][M]>;
/** The same operation as sent: fields with a default are optional. */
type InputOperation<P extends keyof paths, M extends HttpMethod> = P extends keyof inputPaths
  ? NonNullable<inputPaths[P][M]>
  : never;

type Json<R> = R extends { content: { "application/json": infer B } } ? B : void;

/** What a successful call answers (its 200 JSON); ``void`` for a 204. */
export type ResponseOf<O> = O extends { responses: { 200: infer R } }
  ? Json<R>
  : O extends { responses: { 204: unknown } }
    ? void
    : unknown;

/** The path parameters (``never``: the path has none). */
export type PathParamsOf<O> = O extends { parameters: { path: infer P } } ? P : never;

/** The query parameters (``never``: none). */
export type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

/** The JSON body: ``never`` when there is none, ``| undefined`` when it is optional. */
export type BodyOf<O> = O extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : O extends { requestBody?: never }
    ? never
    : O extends { requestBody?: { content: { "application/json": infer B } } }
      ? B | undefined
      : never;

type PathPart<O> = [PathParamsOf<O>] extends [never] ? { path?: undefined } : { path: PathParamsOf<O> };
type QueryPart<O> = [QueryOf<O>] extends [never] ? { query?: undefined } : { query?: QueryOf<O> };
type BodyPart<O> = [BodyOf<O>] extends [never]
  ? { body?: undefined }
  : undefined extends BodyOf<O>
    ? { body?: BodyOf<O> }
    : { body: BodyOf<O> };

/** What a call of ``M`` on ``P`` takes besides the path; ``body`` only where ``M`` sends one. */
export type CallOptions<P extends keyof paths, M extends HttpMethod, O = InputOperation<P, M>> = PathPart<O> &
  QueryPart<O> &
  (M extends "get" | "delete" ? unknown : BodyPart<O>) & { signal?: AbortSignal };

/** The options argument, which may be left out when nothing in it is required. */
export type CallArgs<P extends keyof paths, M extends HttpMethod> =
  Record<string, never> extends CallOptions<P, M> ? [options?: CallOptions<P, M>] : [options: CallOptions<P, M>];

type QueryValue = string | number | boolean | null | undefined;

/** ``template`` with each ``{name}`` replaced by its encoded value, then the query (keys in
 * order; null and undefined left out; an array gives the key once per value). Both are
 * encoded with ``encodeURIComponent`` (a space is ``%20``). */
export function buildUrl(
  template: string,
  path?: Record<string, string | number>,
  query?: Record<string, QueryValue | readonly QueryValue[]>,
): string {
  const url = template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = path?.[name];
    if (value === undefined) throw new Error(`${template}: no value for {${name}}`);
    return encodeURIComponent(String(value));
  });
  const pairs: string[] = [];
  for (const [key, value] of Object.entries(query ?? {})) {
    for (const v of Array.isArray(value) ? value : [value]) {
      if (v !== null && v !== undefined) pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`);
    }
  }
  return pairs.length ? `${url}?${pairs.join("&")}` : url;
}
