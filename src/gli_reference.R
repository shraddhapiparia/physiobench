# GLI Global (2022) race-neutral reference values for NHANES 2011-2012 spirometry.
#
# Input : data/processed/spirometry_intermediate.csv   (from prepare_spirometry.py)
# Output: data/processed/gli_reference.csv              (keyed by SEQN)
# Checks: data/reference/gli_global_validation_cases.csv
#
# Uses rspiro::pred_GLIgl / LLN_GLIgl / zscore_GLIgl (Bowerman et al.,
# AJRCCM 2023;207:768-774). Per the rspiro documentation:
#   age    : years (lookup covers 3-95; NA outside)
#   height : metres (converted to cm inside rspiro)
#   gender : 1 = male, 2 = female   (same coding as NHANES RIAGENDR)
#   FEV1, FVC in litres; FEV1FVC as a fraction
# LLN is the 5th percentile (z = -1.645).
#
# Age: NHANES RIDAGEYR is whole years (no decimal age is public for adults), so
# true age is up to ~1 year older than the value used. rspiro looks up splines
# at floor(age*4)/4, which is exact for whole-year ages.
# Height: participants with BMIHT=3 ("not straight") are retained and flagged
# as height_not_straight for a later sensitivity analysis.
#
# No imputation: predictions are NA when age, sex, or height is unavailable or
# out of range; z-scores are additionally NA when the measurement is missing.
# No BDR or obstruction classification is produced here.
#
# Output also carries the baseline exam status and FEV1/FVC quality grades;
# z-scores must not be interpreted without them. Observed values that are
# zero, negative, or non-finite get no z-score.
#
# Usage: Rscript src/gli_reference.R   (paths resolve from the script, so any
# working directory works)

suppressPackageStartupMessages(library(rspiro))

# Resolve paths from this script's location so it runs from any directory.
script_file <- sub("^--file=", "", grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE))
ROOT <- if (length(script_file) == 1) normalizePath(file.path(dirname(script_file), "..")) else getwd()
IN_PATH    <- file.path(ROOT, "data/processed/spirometry_intermediate.csv")
OUT_PATH   <- file.path(ROOT, "data/processed/gli_reference.csv")
CASES_PATH <- file.path(ROOT, "data/reference/gli_global_validation_cases.csv")
N_EXPECTED <- 7495
AGE_RANGE  <- c(3, 95)   # rows in rspiro's GLIgl lookup table
Z_LLN      <- qnorm(0.05) # -1.644854; rspiro uses the rounded 1.645

# Validation-case rules (V1). The CSV tolerance may tighten MAX_TOL, never widen it.
CASE_IDS   <- c("C1", "C2", "C3", "C4")
SOURCES    <- c("independent_python", "gli_calculator")
INPUT_COLS <- c("sex", "age", "height_cm", "fev1_L", "fvc_L")
MAX_TOL    <- 0.01
HALF_3DP   <- 0.0005 + 1e-9  # calculator shows 3 dp; covers either half-way rounding rule

cat(sprintf("R %s | rspiro %s\n\n", getRversion(), packageVersion("rspiro")))

# --------------------------------------------------------------------------- #
# Load and pre-calculation integrity checks
# --------------------------------------------------------------------------- #
d <- read.csv(IN_PATH, stringsAsFactors = FALSE)

required <- c("SEQN", "RIDAGEYR", "RIAGENDR", "height_m", "fev1_pre_L", "fvc_pre_L",
              "BMIHT", "SPXNSTAT", "SPDBRONC", "is_adult", "height_not_straight",
              "SPXNQFV1", "SPXNQFVC", "fev1_pre_grade_AB", "fvc_pre_grade_AB",
              "pre_partial_no_values", "pre_excluded_with_values")
missing_cols <- setdiff(required, names(d))
if (length(missing_cols)) stop("Missing required columns: ", paste(missing_cols, collapse = ", "))

stopifnot(nrow(d) == N_EXPECTED, !anyDuplicated(d$SEQN), !anyNA(d$SEQN))

# Discordant record: safety exclusion with measured values; status must be unchanged.
x <- d[d$SEQN == 68442, ]
stopifnot(nrow(x) == 1, x$SPXNSTAT == 4, !is.na(x$fev1_pre_L), !is.na(x$fvc_pre_L),
          isTRUE(as.logical(x$pre_excluded_with_values)))

# 44 partial exams without values keep CDC SPDBRONC = 2 (recorded status only;
# their data are not sufficient for physiological interpretation).
p <- d[as.logical(d$pre_partial_no_values), ]
stopifnot(nrow(p) == 44, all(p$SPDBRONC == 2), all(is.na(p$fev1_pre_L)), all(is.na(p$fvc_pre_L)))

cat("Pre-calculation checks passed: 7,495 unique SEQN; SEQN 68442 retains SPXNSTAT=4 with values;",
    "44 partial exams retain SPDBRONC=2 with no measurements.\n\n")

# --------------------------------------------------------------------------- #
# Inputs and availability
# --------------------------------------------------------------------------- #
age    <- d$RIDAGEYR
sex    <- d$RIAGENDR
height <- d$height_m

reason <- ifelse(is.na(age) | age < AGE_RANGE[1] | age > AGE_RANGE[2], "age outside 3-95",
          ifelse(is.na(sex) | !(sex %in% c(1, 2)), "sex missing/invalid",
          ifelse(is.na(height), "height missing", "")))
ok <- reason == ""

fev1  <- d$fev1_pre_L
fvc   <- d$fvc_pre_L
# Observed values must be finite and > 0 to give a z-score. Missing stays
# missing; zero, negative, or infinite values are rejected (z = NA, reason
# recorded) while predictions and LLN are still produced.
valid_obs <- function(x) is.finite(x) & x > 0
fev1_ok <- valid_obs(fev1)
fvc_ok  <- valid_obs(fvc)
invalid_obs <- (!is.na(fev1) & !fev1_ok) | (!is.na(fvc) & !fvc_ok)
ratio <- ifelse(fev1_ok & fvc_ok, fev1 / fvc, NA_real_)

# --------------------------------------------------------------------------- #
# GLI Global calculations (only on rows with valid inputs; others stay NA)
# --------------------------------------------------------------------------- #
params <- c("FEV1", "FVC", "FEV1FVC")
out_names <- c(FEV1 = "fev1", FVC = "fvc", FEV1FVC = "fev1fvc")

res <- data.frame(SEQN = d$SEQN)
for (p in params) {
  pred <- lln <- rep(NA_real_, nrow(d))
  pred[ok] <- pred_GLIgl(age[ok], height[ok], sex[ok], param = p)
  lln[ok]  <- LLN_GLIgl(age[ok], height[ok], sex[ok], param = p)
  res[[paste0("gli_", out_names[p], "_pred")]] <- pred
  res[[paste0("gli_", out_names[p], "_lln")]]  <- lln
}

obs <- list(FEV1 = ifelse(fev1_ok, fev1, NA_real_),
            FVC  = ifelse(fvc_ok,  fvc,  NA_real_),
            FEV1FVC = ratio)
for (p in params) {
  z <- rep(NA_real_, nrow(d))
  has <- ok & !is.na(obs[[p]])
  args <- list(age = age[has], height = height[has], gender = sex[has])
  args[[p]] <- obs[[p]][has]
  z[has] <- do.call(zscore_GLIgl, args)
  res[[paste0("gli_", out_names[p], "_z")]] <- z
}

z_reason <- ifelse(!ok, reason,
            ifelse(invalid_obs, "invalid baseline FEV1/FVC (<=0 or non-finite)",
            ifelse(is.na(ratio), "no baseline FEV1/FVC", "")))

# Baseline quality grades carried into the output so z-scores are never used
# without them. Python writes missing grades as "" and booleans as True/False.
grade <- function(x) ifelse(is.na(x) | x == "", NA_character_, x)
fev1_grade_AB <- as.logical(d$fev1_pre_grade_AB)
fvc_grade_AB  <- as.logical(d$fvc_pre_grade_AB)

out <- data.frame(
  SEQN                = d$SEQN,
  age                 = age,
  sex                 = sex,
  height_m            = height,
  fev1_pre_L          = fev1,
  fvc_pre_L           = fvc,
  fev1fvc_pre         = ratio,
  is_adult            = as.logical(d$is_adult),
  height_not_straight = as.logical(d$height_not_straight),  # BMIHT=3, for sensitivity analysis
  SPXNSTAT            = d$SPXNSTAT,             # baseline exam status (CDC code)
  SPXNQFV1            = grade(d$SPXNQFV1),      # baseline FEV1 grade A-F
  SPXNQFVC            = grade(d$SPXNQFVC),      # baseline FVC grade A-F
  fev1_pre_grade_AB   = fev1_grade_AB,
  fvc_pre_grade_AB    = fvc_grade_AB,
  # FEV1/FVC needs both grades; NA if a grade is missing (R three-valued AND).
  fev1fvc_pre_grades_AB = fev1_grade_AB & fvc_grade_AB,
  gli_pred_available  = ok,
  gli_pred_missing_reason = reason,
  gli_z_missing_reason    = z_reason
)
out <- cbind(out, res[, setdiff(names(res), "SEQN")])

stopifnot(nrow(out) == N_EXPECTED, !anyDuplicated(out$SEQN), identical(out$SEQN, d$SEQN))

# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
cat("Validation\n----------\n")
fails <- 0

# V1. Reference cases: official GLI calculator and independent implementation.
#     Every value must be present and finite; anything missing fails.
cases <- read.csv(CASES_PATH, comment.char = "#", colClasses = "character")
cols <- c("fev1_pred", "fev1_lln", "fev1_z", "fvc_pred", "fvc_lln", "fvc_z",
          "fev1fvc_pred", "fev1fvc_lln", "fev1fvc_z")
v1_fail <- function(msg) { cat("V1 FAIL", msg, "\n"); fails <<- fails + 1 }

# Structure: exactly one row per case C1-C4 for each source; no other labels.
bad_src <- setdiff(unique(cases$source), SOURCES)
if (length(bad_src)) v1_fail(paste("unexpected source label(s):", paste(bad_src, collapse = ", ")))
for (s in SOURCES) {
  ids <- sort(cases$case_id[cases$source == s])
  if (!identical(ids, CASE_IDS))
    v1_fail(sprintf("%s rows must be exactly %s; found [%s]", s,
                    paste(CASE_IDS, collapse = ","), paste(ids, collapse = ",")))
}

# Paired rows must have identical inputs.
for (id in CASE_IDS) {
  pair <- lapply(SOURCES, function(s) cases[cases$case_id == id & cases$source == s, INPUT_COLS])
  if (all(sapply(pair, nrow) == 1) &&
      !isTRUE(all(as.numeric(unlist(pair[[1]])) == as.numeric(unlist(pair[[2]])))))
    v1_fail(sprintf("%s inputs differ between %s and %s rows", id, SOURCES[1], SOURCES[2]))
}

for (i in seq_len(nrow(cases))) {
  cs <- cases[i, ]
  label <- sprintf("V1 %s %-19s", cs$case_id, cs$source)
  inp      <- setNames(suppressWarnings(as.numeric(unlist(cs[INPUT_COLS]))), INPUT_COLS)
  expected <- suppressWarnings(as.numeric(unlist(cs[cols])))
  csv_tol  <- suppressWarnings(as.numeric(cs$tolerance))
  tol      <- min(c(csv_tol[is.finite(csv_tol) & csv_tol > 0], MAX_TOL))

  if (!all(is.finite(inp))) {
    cat(label, "FAIL (missing or non-finite inputs)\n"); fails <- fails + 1; next
  }
  if (!all(is.finite(expected))) {
    cat(label, sprintf("FAIL (%d/%d expected values missing or non-finite)\n",
                       sum(!is.finite(expected)), length(cols)))
    fails <- fails + 1; next
  }
  # Calculator entries are display values; more than 3 decimals suggests they
  # were copied from a computed source rather than the calculator.
  if (cs$source == "gli_calculator" && any(abs(expected * 1000 - round(expected * 1000)) > 1e-9)) {
    cat(label, "FAIL (values have >3 decimals; enter calculator display values)\n")
    fails <- fails + 1; next
  }

  a <- inp[["age"]]; h <- inp[["height_cm"]] / 100; g <- inp[["sex"]]
  got <- c(
    pred_GLIgl(a, h, g, "FEV1"), LLN_GLIgl(a, h, g, "FEV1"),
    zscore_GLIgl(a, h, g, FEV1 = inp[["fev1_L"]]),
    pred_GLIgl(a, h, g, "FVC"), LLN_GLIgl(a, h, g, "FVC"),
    zscore_GLIgl(a, h, g, FVC = inp[["fvc_L"]]),
    pred_GLIgl(a, h, g, "FEV1FVC"), LLN_GLIgl(a, h, g, "FEV1FVC"),
    zscore_GLIgl(a, h, g, FEV1FVC = inp[["fev1_L"]] / inp[["fvc_L"]]))
  if (length(got) != length(cols) || !all(is.finite(got))) {
    cat(label, sprintf("FAIL (%d/%d rspiro values missing or non-finite)\n",
                       sum(!is.finite(got)), length(cols)))
    fails <- fails + 1; next
  }

  diff <- abs(got - expected)
  bad  <- diff > tol
  # The calculator displays true values rounded to 3 dp, so rspiro must lie
  # within half a unit of the 3rd decimal of each displayed value.
  if (cs$source == "gli_calculator") bad <- bad | diff > HALF_3DP
  cat(label, if (any(bad)) "FAIL" else "PASS",
      sprintf("(%d/%d compared, max |diff| %.2e, tol %g%s)", length(diff), length(cols), max(diff),
              tol, if (cs$source == "gli_calculator") ", 3-dp rounding check" else ""), "\n")
  if (any(bad)) {
    fails <- fails + 1
    print(rbind(expected = expected, rspiro = got, abs_diff = diff)[, bad, drop = FALSE])
  }
}

# V2. Vectorised results equal one-row-at-a-time results (guards row ordering
#     inside rspiro's merge/reshape).
set.seed(20111)
idx <- sample(which(ok & !is.na(ratio)), 25)
one <- t(sapply(idx, function(i) c(
  pred_GLIgl(age[i], height[i], sex[i], "FEV1"),
  LLN_GLIgl(age[i], height[i], sex[i], "FVC"),
  zscore_GLIgl(age[i], height[i], sex[i], FEV1FVC = ratio[i]))))
vec <- cbind(out$gli_fev1_pred[idx], out$gli_fvc_lln[idx], out$gli_fev1fvc_z[idx])
v2 <- max(abs(one - vec))
cat(sprintf("V2 vectorised vs per-row (25 rows)         %s (max |diff| %.1e)\n",
            if (v2 < 1e-12) "PASS" else "FAIL", v2))
if (v2 >= 1e-12) fails <- fails + 1

# V3. Internal identities: z(pred) = 0 and z(LLN) = -1.645 for every row.
r <- which(ok)
z_at_pred <- zscore_GLIgl(age[r], height[r], sex[r], FEV1FVC = out$gli_fev1fvc_pred[r])
z_at_lln  <- zscore_GLIgl(age[r], height[r], sex[r], FEV1FVC = out$gli_fev1fvc_lln[r])
v3 <- max(abs(z_at_pred), abs(z_at_lln + 1.645))
cat(sprintf("V3 z(pred)=0, z(LLN)=-1.645, n=%d        %s (max dev %.1e)\n",
            length(r), if (v3 < 1e-9) "PASS" else "FAIL", v3))
if (v3 >= 1e-9) fails <- fails + 1

# V4. FEV1/FVC < LLN agrees with z < -1.645 (rspiro's LLN constant).
k <- which(!is.na(out$gli_fev1fvc_z))
below_lln <- out$fev1fvc_pre[k] < out$gli_fev1fvc_lln[k]
below_z   <- out$gli_fev1fvc_z[k] < -1.645
disagree  <- which(below_lln != below_z)
near      <- abs(out$gli_fev1fvc_z[k][disagree] + 1.645) < 1e-9
cat(sprintf("V4 ratio<LLN vs z<-1.645, n=%d            %s (%d disagree; %d of them within 1e-9 of threshold)\n",
            length(k), if (all(near)) "PASS" else "FAIL", length(disagree), sum(near)))
if (!all(near)) fails <- fails + 1
n_between <- sum(out$gli_fev1fvc_z[k] < -1.645 & out$gli_fev1fvc_z[k] >= Z_LLN)
cat(sprintf("   note: rows with z in [%.6f, -1.645) (i.e. affected by rounding 1.6449 -> 1.645): %d\n",
            Z_LLN, n_between))

# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
summarise <- function(sel, label) {
  s <- out[sel, ]
  cat(sprintf("\n%s: n = %d\n", label, nrow(s)))
  cat(sprintf("  predictions available    %d\n", sum(s$gli_pred_available)))
  cat("  prediction missing reasons:"); print(table(s$gli_pred_missing_reason[!s$gli_pred_available]))
  cat(sprintf("  FEV1/FVC z-scores        %d\n", sum(!is.na(s$gli_fev1fvc_z))))
  cat("  z-score missing reasons:"); print(table(s$gli_z_missing_reason[s$gli_z_missing_reason != ""]))
  cat(sprintf("  height_not_straight with predictions: %d\n",
              sum(s$height_not_straight & s$gli_pred_available)))
  num <- grep("^gli_.*_(pred|lln|z)$", names(s), value = TRUE)
  rng <- t(sapply(num, function(v) c(min = min(s[[v]], na.rm = TRUE),
                                      median = median(s[[v]], na.rm = TRUE),
                                      max = max(s[[v]], na.rm = TRUE),
                                      n = sum(!is.na(s[[v]])))))
  print(round(rng, 3))
}
summarise(rep(TRUE, nrow(out)), "Full spirometry cohort (ages 6-79)")
summarise(out$is_adult %in% TRUE, "Adults (RIDAGEYR >= 18)")

# Fail before writing so a failed run never overwrites existing output.
if (fails > 0) {
  cat(sprintf("\n%d validation check(s) FAILED; %s not written\n", fails, OUT_PATH))
  quit(status = 1)
}

write.csv(out, OUT_PATH, row.names = FALSE, na = "")
cat(sprintf("\nWrote %s (%d rows x %d columns)\n", OUT_PATH, nrow(out), ncol(out)))
