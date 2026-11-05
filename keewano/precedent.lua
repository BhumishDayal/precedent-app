-- Precedent table inside Keewano: for every (drive model, warning pattern), how many warned drives
-- died within 30 days. Each drive is a Keewano entity whose events are DriveModel, WarningPattern,
-- DriveFailed and Decision (pushed by precedent/keewano.py).

local MODEL   = kdb.resolve_event_id("DriveModel")
local PATTERN = kdb.resolve_event_id("WarningPattern")
local FAILED  = kdb.resolve_event_id("DriveFailed")
local HORIZON = 30 * 86400
local MIN_N   = 10

partial = {}   -- partial[model_data][pattern_data] = {n, died}; bounded by models x patterns
output = {}

function process_user(user, events)
  local count = events.count
  local fi = events:find_next(0, FAILED, count)
  local failed_ts = -1
  if fi < count then failed_ts = events[fi].timestamp end

  local mi = events:find_next(0, MODEL, count)
  if mi == count then return end
  local model = events[mi].data

  local byp = partial[model]
  if byp == nil then byp = {}; partial[model] = byp end

  local i = events:find_next(0, PATTERN, count)
  while i < count do
    local ev = events[i]
    local c = byp[ev.data]
    if c == nil then c = {n = 0, died = 0}; byp[ev.data] = c end
    c.n = c.n + 1
    if failed_ts >= ev.timestamp and failed_ts - ev.timestamp <= HORIZON then c.died = c.died + 1 end
    i = events:find_next(i + 1, PATTERN, count)
  end
end

function reduce(partials)
  local acc = {}
  for _, p in ipairs(partials) do
    for model, byp in pairs(p) do
      local m = acc[model]
      if m == nil then m = {}; acc[model] = m end
      for pat, c in pairs(byp) do
        local t = m[pat]
        if t == nil then t = {n = 0, died = 0}; m[pat] = t end
        t.n = t.n + c.n
        t.died = t.died + c.died
      end
    end
  end
  local rows = {}
  for model, m in pairs(acc) do
    for pat, t in pairs(m) do
      if t.n >= MIN_N then
        rows[#rows + 1] = {
          model = kdb.event_data_text(MODEL, model),
          pattern = kdb.event_data_text(PATTERN, pat),
          n = t.n, died = t.died, rate = t.died / t.n,
        }
      end
    end
  end
  output.rows = rows
end
