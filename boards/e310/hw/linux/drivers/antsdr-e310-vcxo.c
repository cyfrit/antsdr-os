// SPDX-License-Identifier: GPL-2.0-only
/*
 * ANTSDR E310 FPGA VCXO control
 *
 * Copyright (C) 2023 MicroPhase Inc.
 * Copyright (C) 2026 ANTSDR Firmware contributors
 */

#include <linux/bits.h>
#include <linux/device.h>
#include <linux/iio/iio.h>
#include <linux/iio/sysfs.h>
#include <linux/io.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/platform_device.h>

#define E310_VCXO_CONTROL	0x00
#define E310_VCXO_MANUAL_DAC	0x04
#define E310_VCXO_ACTIVE_DAC	0x08
#define E310_VCXO_REFERENCE	0x0c
#define E310_VCXO_STATUS		0x10

#define E310_VCXO_CONTROL_MANUAL	BIT(0)
#define E310_VCXO_STATUS_LOCKED	BIT(0)
#define E310_VCXO_STATUS_10MHZ	BIT(1)
#define E310_VCXO_STATUS_PPS	BIT(2)

enum e310_vcxo_attribute {
	E310_ATTR_MODE,
	E310_ATTR_MANUAL_DAC,
	E310_ATTR_ACTIVE_DAC,
	E310_ATTR_REFERENCE,
	E310_ATTR_LOCKED,
	E310_ATTR_REFERENCE_10MHZ,
	E310_ATTR_REFERENCE_PPS,
};

struct e310_vcxo_state {
	void __iomem *base;
};

static ssize_t e310_vcxo_show(struct device *dev,
			      struct device_attribute *attribute, char *buffer)
{
	struct iio_dev *indio_dev = dev_to_iio_dev(dev);
	struct e310_vcxo_state *state = iio_priv(indio_dev);
	struct iio_dev_attr *this_attribute = to_iio_dev_attr(attribute);
	u32 value;

	switch (this_attribute->address) {
	case E310_ATTR_MODE:
		value = !!(readl(state->base + E310_VCXO_CONTROL) &
			   E310_VCXO_CONTROL_MANUAL);
		break;
	case E310_ATTR_MANUAL_DAC:
		value = readl(state->base + E310_VCXO_MANUAL_DAC) & 0xffff;
		break;
	case E310_ATTR_ACTIVE_DAC:
		value = readl(state->base + E310_VCXO_ACTIVE_DAC) & 0xffff;
		break;
	case E310_ATTR_REFERENCE:
		value = readl(state->base + E310_VCXO_REFERENCE) & 0x3;
		break;
	case E310_ATTR_LOCKED:
		value = !!(readl(state->base + E310_VCXO_STATUS) &
			   E310_VCXO_STATUS_LOCKED);
		break;
	case E310_ATTR_REFERENCE_10MHZ:
		value = !!(readl(state->base + E310_VCXO_STATUS) &
			   E310_VCXO_STATUS_10MHZ);
		break;
	case E310_ATTR_REFERENCE_PPS:
		value = !!(readl(state->base + E310_VCXO_STATUS) &
			   E310_VCXO_STATUS_PPS);
		break;
	default:
		return -EINVAL;
	}

	return sysfs_emit(buffer, "%u\n", value);
}

static ssize_t e310_vcxo_store(struct device *dev,
			       struct device_attribute *attribute,
			       const char *buffer, size_t length)
{
	struct iio_dev *indio_dev = dev_to_iio_dev(dev);
	struct e310_vcxo_state *state = iio_priv(indio_dev);
	struct iio_dev_attr *this_attribute = to_iio_dev_attr(attribute);
	u32 value;
	int ret;

	ret = kstrtou32(buffer, 0, &value);
	if (ret)
		return ret;

	switch (this_attribute->address) {
	case E310_ATTR_MODE:
		if (value > 1)
			return -ERANGE;
		writel(value, state->base + E310_VCXO_CONTROL);
		break;
	case E310_ATTR_MANUAL_DAC:
		if (value > 0xffff)
			return -ERANGE;
		writel(value, state->base + E310_VCXO_MANUAL_DAC);
		break;
	case E310_ATTR_REFERENCE:
		if (value > 2)
			return -ERANGE;
		writel(value, state->base + E310_VCXO_REFERENCE);
		break;
	default:
		return -EINVAL;
	}

	return length;
}

static IIO_DEVICE_ATTR(in_voltage_dac_mode, 0644,
			       e310_vcxo_show, e310_vcxo_store,
			       E310_ATTR_MODE);
static IIO_DEVICE_ATTR(in_voltage_dac_value, 0644,
			       e310_vcxo_show, e310_vcxo_store,
			       E310_ATTR_MANUAL_DAC);
static IIO_DEVICE_ATTR(in_voltage_dac_read_value, 0444,
			       e310_vcxo_show, NULL,
			       E310_ATTR_ACTIVE_DAC);
static IIO_DEVICE_ATTR(in_voltage_dac_ref_sel, 0644,
			       e310_vcxo_show, e310_vcxo_store,
			       E310_ATTR_REFERENCE);
static IIO_DEVICE_ATTR(in_voltage_dac_locked, 0444,
			       e310_vcxo_show, NULL,
			       E310_ATTR_LOCKED);
static IIO_DEVICE_ATTR(in_voltage_dac_ref_is_10mhz, 0444,
			       e310_vcxo_show, NULL,
			       E310_ATTR_REFERENCE_10MHZ);
static IIO_DEVICE_ATTR(in_voltage_dac_ref_is_pps, 0444,
			       e310_vcxo_show, NULL,
			       E310_ATTR_REFERENCE_PPS);

static struct attribute *e310_vcxo_attributes[] = {
	&iio_dev_attr_in_voltage_dac_mode.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_value.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_read_value.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_ref_sel.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_locked.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_ref_is_10mhz.dev_attr.attr,
	&iio_dev_attr_in_voltage_dac_ref_is_pps.dev_attr.attr,
	NULL,
};

static const struct attribute_group e310_vcxo_attribute_group = {
	.attrs = e310_vcxo_attributes,
};

static int e310_vcxo_read_raw(struct iio_dev *indio_dev,
			      const struct iio_chan_spec *channel,
			      int *value, int *value2, long mask)
{
	struct e310_vcxo_state *state = iio_priv(indio_dev);

	if (mask != IIO_CHAN_INFO_RAW)
		return -EINVAL;

	*value = readl(state->base + E310_VCXO_ACTIVE_DAC) & 0xffff;
	return IIO_VAL_INT;
}

static int e310_vcxo_write_raw(struct iio_dev *indio_dev,
			       const struct iio_chan_spec *channel,
			       int value, int value2, long mask)
{
	struct e310_vcxo_state *state = iio_priv(indio_dev);

	if (mask != IIO_CHAN_INFO_RAW)
		return -EINVAL;
	if (value < 0 || value > 0xffff || value2)
		return -ERANGE;

	writel(value, state->base + E310_VCXO_MANUAL_DAC);
	return 0;
}

static const struct iio_info e310_vcxo_info = {
	.read_raw = e310_vcxo_read_raw,
	.write_raw = e310_vcxo_write_raw,
	.attrs = &e310_vcxo_attribute_group,
};

static const struct iio_chan_spec e310_vcxo_channels[] = {
	{
		.type = IIO_VOLTAGE,
		.indexed = 1,
		.output = 1,
		.channel = 0,
		.info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
	},
};

static int e310_vcxo_probe(struct platform_device *pdev)
{
	struct e310_vcxo_state *state;
	struct iio_dev *indio_dev;

	indio_dev = devm_iio_device_alloc(&pdev->dev, sizeof(*state));
	if (!indio_dev)
		return -ENOMEM;

	state = iio_priv(indio_dev);
	state->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(state->base))
		return PTR_ERR(state->base);

	indio_dev->name = "e310-vcxo-control";
	indio_dev->dev.parent = &pdev->dev;
	indio_dev->info = &e310_vcxo_info;
	indio_dev->modes = INDIO_DIRECT_MODE;
	indio_dev->channels = e310_vcxo_channels;
	indio_dev->num_channels = ARRAY_SIZE(e310_vcxo_channels);

	return devm_iio_device_register(&pdev->dev, indio_dev);
}

static const struct of_device_id e310_vcxo_of_match[] = {
	{ .compatible = "microphase,antsdr-e310-vcxo" },
	{ }
};
MODULE_DEVICE_TABLE(of, e310_vcxo_of_match);

static struct platform_driver e310_vcxo_driver = {
	.probe = e310_vcxo_probe,
	.driver = {
		.name = "antsdr-e310-vcxo",
		.of_match_table = e310_vcxo_of_match,
	},
};
module_platform_driver(e310_vcxo_driver);

MODULE_AUTHOR("ANTSDR Firmware contributors");
MODULE_DESCRIPTION("ANTSDR E310 FPGA VCXO control");
MODULE_LICENSE("GPL");
