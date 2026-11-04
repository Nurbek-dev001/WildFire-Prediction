# Defense speech: two speakers

Nurbek opens (slides 1-6) and closes (slides 21-24) with the descriptive parts. Samat presents the data processing, methods and results (slides 7-20).

Speaking time at about 130 words per minute: Nurbek ~6 min (810 words), Samat ~9 min (1226 words), together ~16 min.

The same lines are in the speaker notes of each slide (PowerPoint: Slide Show > Presenter View).

Tips: look at the commission, not at the screen; point at the number you are talking about; hand over with the prepared sentence ("Thank you, Nurbek / Samat").

## Slide 1 - Title (Nurbek)

Good afternoon, dear members of the commission. My name is Nurbek Bolarbek, and this is my colleague Samat Zharylkap. Today we present our research: "An Explainable Multisource Machine Learning Framework for Next-Day Wildfire Prediction and Mapping in Kazakhstan".
In simple words, we tried to answer one question: which places in Kazakhstan are most likely to have a new fire tomorrow? The map on the right is a real forecast of our model for 8 June 2023. Dark red means a higher chance of a new fire.

## Slide 2 - Problem statement (Nurbek)

Why is this important? In June 2023, a large fire started in the Semei Ormany forest reserve in Abay Region, and fourteen forestry workers died.
This is not a single case. Satellites see about sixteen thousand new fire starts in Kazakhstan every year. The country is very big: we divided it into 110,129 squares of five by five kilometres, and nobody can watch all of them every day.
So the aim of our study was to build and honestly test a model that, every day, estimates the chance of a new fire in each square for the next day, and explains why the chance is high.

## Slide 3 - Input and output (Nurbek)

This slide shows our task as input and output.
The input is seven kinds of data: satellite fire detections, weather, vegetation, land cover, terrain, people and the season.
The model learns from the years 2015 to 2021 which conditions came before new fires.
The output is, for every square and every day, the chance of a new fire tomorrow. We show it as a daily map with four warning levels.

## Slide 4 - Research questions (Nurbek)

We had three research questions.
First: is more data better than simple rules?
Second: does the model still work next year and in a new place?
Third: can we trust its numbers, and why does it say "high risk"?
We will come back to these three questions at the end of the presentation.

## Slide 5 - Data sources (Nurbek)

Now about the data. We joined seven open data sources on one five-kilometre grid. Fire detections come from NASA's VIIRS satellite sensor. Weather comes from the ERA5 archive, vegetation from NOAA, land cover from MODIS, terrain from SRTM, and population from WorldPop.
One rule was very important for us: the model may only use information that was really available before the forecast day. For example, the weather archive appears about five days late, so we used the weather from seven days before.

## Slide 6 - Raw data (Nurbek)

This is what the raw data look like. Every row is one hot spot seen by the satellite, with its time, latitude, longitude and confidence. The small code cell on the right simply loads the file and counts the rows.
In 2023 alone there were 65,413 such points, and more than one million in ten years. But one fire can create hundreds of points over several days, so we had to group them. My colleague Samat will explain how we did it.

## Slide 7 - From hot spots to fire starts (Samat)

Thank you, Nurbek. To turn hot spots into a clear target, we used four steps.
First, we cleaned the data: we kept only nominal and high-confidence points and removed industrial heat sources such as gas flares.
Second, we linked points that are closer than two kilometres and forty-eight hours, because they belong to the same fire.
Third, we kept only the first day of each fire, because we want to predict new fires, not fires that are already burning.
Fourth, we placed these starts on the five-kilometre grid.
The code shows that about 1.14 million detections became about 152 thousand fire events. After cleaning, we had 139,326 new fire starts as our targets.

## Slide 8 - Processed dataset (Samat)

After processing, every row of the dataset is one square on one day. Here you can see five real rows from June 2023: the land cover, the temperature, the rain in the last fourteen days, the greenness of plants, the elevation and the population. The last column says whether a new fire started there.
In total we have 26 predictors in seven groups.

## Slide 9 - Rare fires (Samat)

An important feature of this problem is that fires are very rare: only about two of every ten thousand square-days have a new fire.
If we kept all rows, the data would be too large. So we kept every fire and only a sample of the days without fire. Each sampled row has a weight, so 189,885 rows in 2023 represent almost forty million square-days.
The chart also shows that fires became less frequent over time, so our test years, 2023 and 2024, were harder than the training years.

## Slide 10 - Models (Samat)

Next, the models. We compared four machine-learning models.
Logistic regression is the simplest one. Random Forest averages the answers of many decision trees. XGBoost and CatBoost are boosting methods: they build trees one after another, and each new tree fixes the mistakes of the previous ones.
To check whether machine learning is really needed, we also used two simple references: the past fire frequency for each month and land cover, and a model that sees only the weather.

## Slide 11 - How we tested (Samat)

We tested the models in a strict way. The years 2015 to 2021 were used for training and for choosing the best model. The year 2022 was used only to calibrate the probabilities. The years 2023 and 2024 were not touched until the final test.
We also did a test in space: we hid whole one-hundred-kilometre blocks of the country, trained on the rest, and predicted the hidden blocks. This shows whether the model can work in a place it has never seen.

## Slide 12 - How we measure success (Samat)

How do we judge a forecast when fires are so rare? Accuracy is not useful: a model that always says "no fire" is right 99.98 percent of the time.
So we used average precision. Imagine that we sort all squares from the most to the least risky. Average precision is high when the real fires are near the top of this list. A random list gets only 0.0002.
We also measured how many new fires fall inside the five percent riskiest area each day, we checked whether the probabilities are honest, and we used SHAP to explain the model. For every result we give 95 percent confidence intervals.

## Slide 13 - Training code (Samat)

Here is the main code. On the left, we take the best settings found by the Optuna search and train XGBoost with the sample weights. The final model has 314 small trees, each at most five levels deep.
On the right, we use only the year 2022 to calibrate the probabilities and to fix the alert threshold, which is 0.047. The test years were not used in this step.

## Slide 14 - Main result (Samat)

Now the results. XGBoost was the best model. Its average precision was 0.0204, which is about 104 times better than a random ranking, and it was clearly better than both simple references. CatBoost was close, and the difference between them was not significant.
The chart on the right is the easiest way to read the result. If we check the five percent riskiest area each day, XGBoost finds 55.6 percent of new fires. The seasonal rule finds only 14.3 percent, and weather alone only 8.4 percent.

## Slide 15 - Curves and evaluation code (Samat)

This slide shows the same result as curves, together with the real Python code that calculated it.
In panel (a), the precision-recall curves of the two boosting models are above the others almost everywhere.
In panel (b), you can see how many new fires we catch when we check more of the daily area: with five percent we find 55.6 percent of new fires, with ten percent 68 percent, and with twenty percent 82.2 percent.

## Slide 16 - Comparison with other studies (Samat)

You may ask why our average precision is only 0.02, when other studies report 0.95 or more.
The reason is the test design. Most studies test on balanced data, where half of the cases are fires. In our test, only two of ten thousand square-days have a fire. When we re-weighted our same predictions to a fifty-fifty balance, without retraining, the average precision became 0.925.
Our ROC-AUC, which does not depend on this balance, is 0.92, close to other studies. So the difference comes from the honest test, not from a weak model.

## Slide 17 - Which information helps (Samat)

Which information really helps? We removed one group of inputs at a time and measured how much the result became worse.
Terrain gave the largest loss, and land cover, people and season also mattered. Weather from seven days before and vegetation did not help.
We think the reason is that most fires in the steppe are started by people, for example when they burn fields and pastures, and old weather cannot show short hot and dry periods.
So our answer to the first research question is yes, with a caveat: more data was better than simple rules, but the gain came mainly from terrain, land cover, people and season.

## Slide 18 - Future years and new regions (Samat)

The second question was about transfer. In future years the model was stable: its average precision was 80 times the random level in 2023 and 181 times in 2024. But in regions that the model had never seen, it fell to only 15 times.
The chart shows big differences between regions. The best results are in Atyrau and Aktobe, and the weakest are in the northern grain regions, where many small cropland fires are hard to predict.
So the answer is mixed: good for future years, weak for new regions.

## Slide 19 - Calibration (Samat)

The third question starts with calibration. The four warning levels order the risk correctly: the highest level covers only five percent of the area but contains 65.8 percent of the new fires.
But the probabilities are 1.2 to 1.8 times too high. The reason is that fires became less frequent: in 2022 there were 2.5 fires per ten thousand square-days, and in 2024 only 1.5. So the levels are useful as an order of risk, but not as exact chances.

## Slide 20 - Explanations (SHAP) (Samat)

Finally, SHAP explains which inputs pushed the forecasts. Population density is the strongest factor, followed by the month and the recent temperature.
The drivers also differ by land cover. In cropland, recent weather matters most, which fits stubble burning after dry days. In grassland, people and season matter most.
Together with the calibration result, this answers our third question: the probabilities are good for ranking but too high in size, and the forecasts are explained mostly by people, season and land surface.
Now Nurbek will show you a real example.

## Slide 21 - June 2023 case (Nurbek)

Thank you, Samat. This is the week when the Semei Ormany fire started, from the seventh to the ninth of June 2023. Each map shows the forecast for one day, and the blue circles are the real new fires.
On these days, 19 to 31 percent of the new fires were inside the top five percent of the area. Many fires in the east were flagged: four of the seven other eastern starts were in the top four percent.
But the start near Semei was only at the 78th percentile, so our model would not have flagged it. This is an honest result: a forecast can help people prepare, but it cannot prevent every fire.

## Slide 22 - Limitations and next steps (Nurbek)

Our study also has limitations. We used one satellite sensor, which shows when a fire was first seen, not the real ignition time. We cannot separate farm burning from wildfires. The weather was seven days old, we had only five tuning trials instead of fifty, and forest fires were too rare to test separately.
In the future, we want to use weather forecasts for the next day, data from several satellites, and separate agricultural burning from wildfires. We also want to recalibrate the probabilities by season and region and compare our forecasts with official fire records.

## Slide 23 - Conclusion (Nurbek)

To conclude. We built a Kazakhstan dataset that joins satellite fires with weather, vegetation, terrain, land cover and people. We compared four machine-learning models with two simple references, tested them on future years and unseen regions, calibrated the probabilities and explained the model with SHAP. We also produced daily probability maps.
The answers to our questions are: yes, more data helps; the model works well in future years but weakly in new regions; and its ranking is good, but the probabilities are too high.
Thus, all tasks set at the beginning of this work were completed.

## Slide 24 - Thank you (Nurbek)

Thank you for your attention. Our daily forecast platform is available at the address on the slide. We are happy to answer your questions.

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
