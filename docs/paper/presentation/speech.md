# Defense speech: two speakers, about 10 minutes

Nurbek opens (slides 1-6) and closes (slides 21-24) with the descriptive parts. Samat presents the data processing, methods and results (slides 7-20).

Speaking time at about 130 words per minute: Nurbek ~3.3 min (426 words), Samat ~4.6 min (601 words), together ~7.9 min of speaking. With pauses and 24 slide changes the talk takes about 10 minutes.

The same lines are in the speaker notes of each slide (PowerPoint: Slide Show > Presenter View). On fast slides (8, 15, 22) say the line and move on.

Tips: look at the commission, not at the screen; point at the number you are talking about; hand over with the prepared sentence ("Samat will explain how" / "Nurbek will now show a real example").

## Slide 1 - Title (Nurbek)

Good afternoon, dear members of the commission. I am Nurbek Bolarbek, and this is my colleague Samat Zharylkap. Our research answers one question: which places in Kazakhstan are most likely to have a new fire tomorrow? The map on the right is a real forecast of our model.

## Slide 2 - Problem statement (Nurbek)

In June 2023, a fire in the Semei Ormany reserve killed fourteen forestry workers. Satellites see about sixteen thousand new fires in Kazakhstan every year, and the country has more than one hundred and ten thousand squares of five kilometres. Nobody can watch all of them. So our aim was a model that every day shows where a new fire is most likely tomorrow, and explains why.

## Slide 3 - Input and output (Nurbek)

The input is seven kinds of data: satellite fire detections, weather, vegetation, land cover, terrain, people and season. The model learns from 2015 to 2021. The output is the chance of a new fire tomorrow for every square, shown as a daily map with four warning levels.

## Slide 4 - Research questions (Nurbek)

We asked three questions. Is more data better than simple rules? Does the model still work next year and in a new place? And can we trust its numbers and explain them?

## Slide 5 - Data sources (Nurbek)

All seven data sources are public, from NASA, ERA5, NOAA, MODIS, SRTM and WorldPop. One rule was important: the model may only use data that existed before the forecast day. The weather archive is about five days late, so we used weather from seven days before.

## Slide 6 - Raw data (Nurbek)

Every raw row is one hot spot seen by the satellite: time, place and confidence. In 2023 alone there were 65,413 points. One fire creates many points, so we had to group them. Samat will explain how.

## Slide 7 - From hot spots to fire starts (Samat)

Thank you, Nurbek. We cleaned the points, linked points closer than two kilometres and forty-eight hours into one fire, and kept only the first day of each fire, because we predict new fires. About 1.14 million detections became 152 thousand events, and after cleaning we had 139,326 new fire starts.

## Slide 8 - Processed dataset (Samat)

After processing, each row is one square on one day, with 26 predictors in seven groups. The last column shows whether a new fire started.

## Slide 9 - Rare fires (Samat)

Fires are very rare: about two in every ten thousand square-days. We kept every fire and a weighted sample of the other days, so 189,885 rows represent almost forty million square-days of 2023. Fires also became less frequent, so the test years were harder.

## Slide 10 - Models (Samat)

We compared four models: logistic regression, Random Forest, XGBoost and CatBoost. XGBoost and CatBoost build trees one after another, and each tree fixes the mistakes of the previous ones. We also used two simple references: past fire frequency and a weather-only model.

## Slide 11 - How we tested (Samat)

Training used 2015 to 2021, calibration used only 2022, and 2023 to 2024 stayed untouched until the final test. We also hid whole one-hundred-kilometre blocks to test the model in places it had never seen.

## Slide 12 - How we measure success (Samat)

Accuracy is useless here, because always saying "no fire" is right 99.98 percent of the time. So we used average precision: if we sort squares from most to least risky, are the real fires near the top? A random list gets only 0.0002. We also count how many fires fall inside the five percent riskiest area each day.

## Slide 13 - Training code (Samat)

This is the main code: XGBoost with the settings found by Optuna, trained with sample weights. Then only 2022 is used to calibrate the probabilities and fix the alert threshold of 0.047.

## Slide 14 - Main result (Samat)

XGBoost was the best model. Its average precision was 0.0204, about 104 times better than random, and clearly better than both references. If we check the five percent riskiest area each day, XGBoost finds 55.6 percent of new fires. The seasonal rule finds 14.3 percent, and weather alone 8.4 percent.

## Slide 15 - Curves and evaluation code (Samat)

The curves and the real Python code confirm this. With ten percent of the area we find 68 percent of new fires, and with twenty percent, 82 percent.

## Slide 16 - Comparison with other studies (Samat)

Other studies report around 0.95 because they test on balanced data, half fires and half not. Our test keeps the real rate. If we re-weight our same predictions to fifty-fifty, average precision becomes 0.925. So the difference is the honest test, not a weak model.

## Slide 17 - Which information helps (Samat)

We removed one group of inputs at a time. Terrain, land cover, people and season mattered most, while week-old weather and vegetation did not help. Most steppe fires are started by people, so place and calendar matter more than old weather. So, for the first question: yes, more data helps, mainly through these four groups.

## Slide 18 - Future years and new regions (Samat)

The model was stable in 2023 and 2024, but in regions it had never seen, its skill fell from 104 to 15 times random. Results are best in Atyrau and Aktobe and weakest in the northern grain regions. So the second answer is mixed: good for future years, weak for new places.

## Slide 19 - Calibration (Samat)

The highest warning level covers five percent of the area but holds 65.8 percent of new fires, so the order of risk is right. But the probabilities are 1.2 to 1.8 times too high, because fires became less frequent after 2022.

## Slide 20 - Explanations (SHAP) (Samat)

SHAP shows that population density, the month and recent temperature drive the forecasts, and the drivers differ between cropland and grassland. So the third answer: good ranking, probabilities too high, explained mostly by people, season and land. Nurbek will now show a real example.

## Slide 21 - June 2023 case (Nurbek)

Thank you, Samat. These are the forecasts for 7 to 9 June 2023. Many eastern fires were in the top five percent of the area, but the Semei start was only at the 78th percentile, so the model would not have flagged it. A forecast helps people prepare, but it cannot catch every fire.

## Slide 22 - Limitations and next steps (Nurbek)

Our limits are one satellite, farm burning mixed with wildfires, and week-old weather. Next, we want to use weather forecasts, more satellites and official fire records.

## Slide 23 - Conclusion (Nurbek)

To conclude, we built the dataset, compared the models, tested them in time and space, calibrated and explained them, and produced daily maps. More data helps, the model works well in future years but weakly in new regions, and its ranking is good but its probabilities are too high. Thus, all tasks of this work were completed.

## Slide 24 - Thank you (Nurbek)

Thank you for your attention. We are happy to answer your questions.

## Likely questions

**Where does your data come from? Is it free?** (Nurbek)

All data are public: NASA satellite fire detections, the ERA5 weather archive, NOAA vegetation data, MODIS land cover, SRTM terrain and WorldPop population. Anyone can download them.

**Can this model be used in real life?** (Nurbek)

Yes, as a daily ranking tool that shows emergency services where to look first. We already run a daily forecast platform. But the probabilities should not be read as exact chances yet.

**Why did the model miss the Semei fire?** (Nurbek)

The model learns from places where fires often start, and the Semei start was not typical. A forecast shows where fires are likely; it cannot catch every single fire.

**Why is your average precision so low?** (Samat)

Because fires are very rare: only 2 of 10,000 square-days. Random ranking gets 0.0002, so our 0.0204 is 104 times better. On a 50/50 balanced test, as in many studies, the same predictions give 0.925.

**Why XGBoost and not deep learning?** (Samat)

Our data are a table of 26 predictors, and boosted trees work very well on tables. XGBoost was best in every validation year. Deep learning needs more data and computing power and is harder to explain.

**Why did you use weather from seven days before?** (Samat)

The ERA5 archive is published about five days late. If we used same-day weather, the test would not be realistic, because that weather is not known on the forecast day.

**How did you make sure the test was fair?** (Samat)

The test years 2023 and 2024 were not used for training, tuning or calibration. The model was chosen on 2019 to 2021, and calibration used only 2022.

**What does SHAP show?** (Samat)

SHAP shows how much each input pushed one forecast up or down. It shows associations that the model learned, not proof of causes.
