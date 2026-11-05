-- Prediction inside Keewano: which drives are most likely to fail next.
-- One pass over every drive's events: learn the failure rate of each (model, warning pattern) from drives
-- whose outcome is known, and remember each still-running drive's latest warning. reduce() then scores
-- every running drive by the failure rate of its latest pattern and returns the riskiest. Nothing is pulled
-- out of the database to compute it.

local MODEL   = kdb.resolve_event_id("DriveModel")
local SERIAL  = kdb.resolve_event_id("DriveSerial")
local PATTERN = kdb.resolve_event_id("WarningPattern")
local FAILED  = kdb.resolve_event_id("DriveFailed")
local HORIZON = 30 * 86400
local MIN_N   = 10
local TOP     = 25

partial = { rates = {}, running = {} }   -- rates[model][pattern] = {n, died}; running[i] = {serial, model, pattern}
output = {}

function process_user(user, events)
  local count = events.count
  local mi = events:find_next(0, MODEL, count)
  if mi == count then return end
  local model = events[mi].data
  local si = events:find_next(0, SERIAL, count)
  local serial = -1
  if si < count then serial = events[si].data end

  local fi = events:find_next(0, FAILED, count)
  local failed_ts = -1
  if fi < count then failed_ts = events[fi].timestamp end

  local byp = partial.rates[model]
  if byp == nil then byp = {}; partial.rates[model] = byp end

  local last_pattern = -1
  local i = events:find_next(0, PATTERN, count)
  while i < count do
    local ev = events[i]
    local c = byp[ev.data]
    if c == nil then c = {n = 0, died = 0}; byp[ev.data] = c end
    c.n = c.n + 1
    if failed_ts >= ev.timestamp and failed_ts - ev.timestamp <= HORIZON then c.died = c.died + 1 end
    last_pattern = ev.data
    i = events:find_next(i + 1, PATTERN, count)
  end

  if failed_ts < 0 and last_pattern >= 0 then
    local r = partial.running
    r[#r + 1] = {serial = serial, model = model, pattern = last_pattern}
  end
end

function reduce(partials)
  local rates = {}
  local running = {}
  for _, p in ipairs(partials) do
    for model, byp in pairs(p.rates) do
      local m = rates[model]
      if m == nil then m = {}; rates[model] = m end
      for pat, c in pairs(byp) do
        local t = m[pat]
        if t == nil then t = {n = 0, died = 0}; m[pat] = t end
        t.n = t.n + c.n
        t.died = t.died + c.died
      end
    end
    for _, d in ipairs(p.running) do running[#running + 1] = d end
  end

  -- score every running drive by its latest pattern's failure rate, keep the TOP riskiest (insertion into a small sorted list)
  local best = {}
  for _, d in ipairs(running) do
    local t = rates[d.model] and rates[d.model][d.pattern]
    if t and t.n >= MIN_N then
      local risk = t.died / t.n
      if #best < TOP or risk > best[#best].risk then
        local row = {d = d, risk = risk, n = t.n, died = t.died}
        local pos = #best + 1
        for k = 1, #best do
          if risk > best[k].risk then pos = k; break end
        end
        for k = #best, pos, -1 do best[k + 1] = best[k] end
        best[pos] = row
        if #best > TOP then best[#best] = nil end
      end
    end
  end

  local rows = {}
  for k = 1, #best do
    local b = best[k]
    rows[k] = {
      serial = (b.d.serial >= 0) and kdb.event_data_text(SERIAL, b.d.serial) or "",
      model = kdb.event_data_text(MODEL, b.d.model),
      pattern = kdb.event_data_text(PATTERN, b.d.pattern),
      risk = b.risk, n = b.n, died = b.died,
    }
  end
  output.at_risk = rows
  output.running_drives_scored = #running
end
